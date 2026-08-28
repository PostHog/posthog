import json
import base64
import hashlib
from ipaddress import ip_address
from typing import cast
from urllib.parse import urlencode

import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.core.cache import cache as real_cache
from django.test import SimpleTestCase
from django.utils.html import escape

import requests
from parameterized import parameterized
from rest_framework.test import APIClient

from posthog.api.oauth.cimd import (
    CIMDFetchError,
    CIMDMetadataDocument,
    CIMDValidationError,
    _fetch_lock_key,
    _resolve_scopes,
    _resolve_verification_token,
    apply_provisioning_defaults,
    enqueue_cimd_refresh_if_stale,
    fetch_and_upsert_cimd_application,
    fetch_cimd_metadata,
    get_or_create_cimd_application,
    is_cimd_client_id,
    refresh_cimd_metadata_task,
    validate_cimd_url,
    validate_fetchable_https_url,
)
from posthog.api.oauth.client_name import sanitize_client_name
from posthog.models import Organization
from posthog.models.oauth import (
    OAuthApplication,
    OAuthApplicationAccessLevel,
    TokenEndpointAuthMethod,
    create_cimd_verification_token,
)
from posthog.models.oauth_provisioning import PartnerTier
from posthog.scopes import OAUTH_SCOPES_HIDDEN, PRIVILEGED_SCOPES

VALID_CIMD_URL = "https://app.example.com/.well-known/oauth-client-metadata.json"


def _make_metadata(url: str = VALID_CIMD_URL, com_posthog: dict | None = None, **overrides: object) -> dict:
    metadata: dict[str, object] = {
        "client_id": url,
        "client_name": "Test MCP Client",
        "redirect_uris": ["http://127.0.0.1:3000/callback"],
        "grant_types": ["authorization_code"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
    }
    if com_posthog is not None:
        metadata["com.posthog"] = com_posthog
    metadata.update(overrides)
    return metadata


CIMD_JWKS_URI = "https://app.example.com/.well-known/jwks.json"


def _metadata_for_auth(with_jwks: bool) -> dict:
    if not with_jwks:
        return _make_metadata()
    return _make_metadata(token_endpoint_auth_method="private_key_jwt", jwks_uri=CIMD_JWKS_URI)


def _captured_events(mock_capture) -> list:
    return [call.kwargs.get("event") for call in mock_capture.call_args_list]


def _register_provisioning_partner(url: str = VALID_CIMD_URL) -> OAuthApplication:
    """Register a CIMD app and opt it into provisioning, skipping the document declaration the
    registration endpoint requires, so a test that is about a partner's config does not also
    have to publish one."""
    app = fetch_and_upsert_cimd_application(url)
    assert app is not None
    return apply_provisioning_defaults(app)


def _document_fetches(mock_get, url: str = VALID_CIMD_URL) -> list:
    """Calls the mocked session made for ``url``.

    The fetch runs on a session with a pinned-IP adapter mounted, so the patch target is
    ``requests.Session.get``, which is process-wide. Unrelated traffic during a request
    (the ClickHouse health ping) lands on the same mock, so counting raw calls would not
    measure the document fetch under test.
    """
    return [call for call in mock_get.call_args_list if call.args and call.args[0] == url]


def _mock_response(metadata: dict | None = None, status_code: int = 200, headers: dict | None = None):
    """Create a mock requests.Response."""

    resp = MagicMock()
    resp.status_code = status_code
    resp.headers = headers or {}
    resp.is_redirect = status_code in (301, 302, 303, 307, 308)
    resp.is_permanent_redirect = status_code in (301, 308)
    resp.close = MagicMock()
    if metadata is not None:
        body = json.dumps(metadata).encode()
        resp.iter_content = MagicMock(return_value=iter([body]))
    else:
        resp.iter_content = MagicMock(return_value=iter([b""]))
    return resp


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://app.example.com/metadata.json", True),
        ("https://app.example.com/.well-known/oauth-client-metadata.json", True),
        ("http://app.example.com/metadata.json", False),
        ("a1b2c3d4e5f6", False),
        ("https://example.com/", False),
        ("https://example.com", False),
        ("https://example.com/metadata.json#section", False),
        ("https://example.com/metadata.json?foo=bar", False),
        ("https://user@example.com/metadata.json", False),
        ("https://user:pass@example.com/metadata.json", False),
        (None, False),
    ],
)
def test_is_cimd_client_id(url, expected):
    assert is_cimd_client_id(url) == expected


@pytest.mark.parametrize(
    "url,expected_error",
    [
        ("http://app.example.com/metadata.json", "CIMD client_id must use HTTPS"),
        ("https://example.com/", "CIMD client_id must include a path component"),
        ("https://example.com/metadata.json#frag", "CIMD client_id must not contain a fragment"),
        ("https://example.com/metadata.json?foo=bar", "CIMD client_id must not contain query parameters"),
        ("https://user@example.com/metadata.json", "CIMD client_id must not contain userinfo"),
        ("https://user:pass@example.com/metadata.json", "CIMD client_id must not contain userinfo"),
    ],
)
def test_validate_cimd_url_rejects_invalid_format(url, expected_error):
    valid, error = validate_cimd_url(url)
    assert valid is False
    assert error == expected_error


@patch("posthog.api.oauth.cimd.is_url_allowed", return_value=(True, None))
def test_validate_cimd_url_accepts_valid(_mock):
    valid, error = validate_cimd_url(VALID_CIMD_URL, perform_dns_check=True)
    assert valid is True
    assert error is None


@pytest.mark.parametrize(
    "mock_return,url,expected_error",
    [
        (
            (False, "Private IP address not allowed"),
            "https://10.0.0.1/metadata.json",
            "URL blocked: Private IP address not allowed",
        ),
        (
            (False, "Local/metadata host"),
            "https://169.254.169.254/metadata.json",
            "URL blocked: Local/metadata host",
        ),
    ],
)
def test_validate_cimd_url_ssrf_blocked(mock_return, url, expected_error):
    with patch("posthog.api.oauth.cimd.is_url_allowed", return_value=mock_return):
        valid, error = validate_cimd_url(url, perform_dns_check=True)
        assert valid is False
        assert error == expected_error


@patch("posthog.security.url_validation.resolve_host_ips", return_value={ip_address("93.184.216.34")})
class TestFetchCimdMetadata(APIBaseTest):
    @patch("posthog.api.oauth.cimd.requests.Session.get")
    def test_success(self, mock_get, _url_mock):
        metadata = _make_metadata()
        mock_get.return_value = _mock_response(metadata, headers={"Cache-Control": "max-age=3600"})
        result, ttl = fetch_cimd_metadata(VALID_CIMD_URL)

        assert "client_name" in result
        self.assertEqual(result["client_name"], "Test MCP Client")
        self.assertEqual(ttl, 3600)

    @patch("posthog.api.oauth.cimd.requests.Session.get")
    def test_client_id_mismatch(self, mock_get, _url_mock):
        metadata = _make_metadata(client_id="https://wrong.example.com/other.json")
        mock_get.return_value = _mock_response(metadata)
        with self.assertRaises(CIMDValidationError) as ctx:
            fetch_cimd_metadata(VALID_CIMD_URL)
        self.assertIn("does not match", str(ctx.exception))

    @patch("posthog.api.oauth.cimd.requests.Session.get")
    def test_too_large(self, mock_get, _url_mock):
        resp = _mock_response(_make_metadata())
        resp.iter_content = MagicMock(return_value=iter([b"x" * 6000]))
        resp.headers = {"Content-Length": "6000"}
        mock_get.return_value = resp
        with self.assertRaises(CIMDValidationError) as ctx:
            fetch_cimd_metadata(VALID_CIMD_URL)
        self.assertIn("limit", str(ctx.exception))

    @patch("posthog.api.oauth.cimd.requests.Session.get")
    def test_invalid_json(self, mock_get, _url_mock):
        resp = _mock_response()
        resp.status_code = 200
        resp.iter_content = MagicMock(return_value=iter([b"not json"]))
        resp.headers = {}
        mock_get.return_value = resp
        with self.assertRaises(CIMDValidationError):
            fetch_cimd_metadata(VALID_CIMD_URL)

    @patch("posthog.api.oauth.cimd.requests.Session.get")
    def test_missing_redirect_uris(self, mock_get, _url_mock):
        metadata = _make_metadata()
        del metadata["redirect_uris"]
        mock_get.return_value = _mock_response(metadata)
        with self.assertRaises(CIMDValidationError) as ctx:
            fetch_cimd_metadata(VALID_CIMD_URL)
        self.assertIn("redirect_uris", str(ctx.exception))

    @patch("posthog.api.oauth.cimd.requests.Session.get")
    def test_redirect_uri_with_whitespace_rejected(self, mock_get, _url_mock):
        metadata = _make_metadata(redirect_uris=["https://legit.com/callback https://attacker.com/steal"])
        mock_get.return_value = _mock_response(metadata)
        with self.assertRaises(CIMDValidationError) as ctx:
            fetch_cimd_metadata(VALID_CIMD_URL)
        self.assertEqual(str(ctx.exception), "redirect_uri must not contain whitespace")

    @patch("posthog.api.oauth.cimd.requests.Session.get")
    def test_non_200_response(self, mock_get, _url_mock):
        mock_get.return_value = _mock_response(status_code=404)
        with self.assertRaises(CIMDFetchError) as ctx:
            fetch_cimd_metadata(VALID_CIMD_URL)
        self.assertIn("404", str(ctx.exception))

    @patch("posthog.api.oauth.cimd.requests.Session.get")
    def test_timeout(self, mock_get, _url_mock):
        mock_get.side_effect = requests.Timeout("Connection timed out")
        with self.assertRaises(CIMDFetchError):
            fetch_cimd_metadata(VALID_CIMD_URL)

    @parameterized.expand([("client_secret_post",), ("client_secret_basic",), ("client_secret_jwt",), ("tls_auth",)])
    @patch("posthog.api.oauth.cimd.requests.Session.get")
    def test_unsupported_auth_method(self, auth_method, mock_get, _url_mock):
        # Only "none" and "private_key_jwt" are supported: CIMD has no ceremony in which a
        # shared secret could be delivered, and anything unrecognized fails closed.
        mock_get.return_value = _mock_response(_make_metadata(token_endpoint_auth_method=auth_method))
        with self.assertRaises(CIMDValidationError) as ctx:
            fetch_cimd_metadata(VALID_CIMD_URL)
        self.assertIn(auth_method, str(ctx.exception))

    @parameterized.expand([("missing_jwks_uri", None), ("non_https_jwks_uri", "http://app.example.com/jwks.json")])
    @patch("posthog.api.oauth.cimd.requests.Session.get")
    def test_private_key_jwt_requires_a_usable_jwks_uri(self, _name, jwks_uri, mock_get, _url_mock):
        metadata = _make_metadata(token_endpoint_auth_method="private_key_jwt")
        if jwks_uri is not None:
            metadata["jwks_uri"] = jwks_uri
        mock_get.return_value = _mock_response(metadata)
        with self.assertRaises(CIMDValidationError):
            fetch_cimd_metadata(VALID_CIMD_URL)

    @parameterized.expand(
        [
            # A jwks_uri names a document rather than identifying the client, so the CIMD
            # client_id shape rules must not apply to it. A versioned key set is legitimate.
            ("query_string", "https://app.example.com/jwks.json?v=2", True),
            ("bare_host", "https://app.example.com", True),
            ("plaintext_http", "http://app.example.com/jwks.json", False),
            ("fragment", "https://app.example.com/jwks.json#k", False),
        ]
    )
    def test_jwks_uri_is_not_held_to_cimd_client_id_shape_rules(self, _url_mock, _name, url, expected_valid):
        valid, _error = validate_fetchable_https_url(url)
        assert valid is expected_valid
        if not expected_valid:
            return
        # The same URL as a client_id is a different question: that one must be a stable
        # identifier, so a query string or a bare host is rejected there.
        assert validate_cimd_url(url)[0] is False

    @patch("posthog.api.oauth.cimd.requests.Session.get")
    def test_cache_ttl_clamped_to_minimum(self, mock_get, _url_mock):
        metadata = _make_metadata()
        mock_get.return_value = _mock_response(metadata, headers={"Cache-Control": "max-age=10"})
        _, ttl = fetch_cimd_metadata(VALID_CIMD_URL)
        self.assertEqual(ttl, 300)  # Clamped to 5 min minimum

    @patch("posthog.api.oauth.cimd.requests.Session.get")
    def test_cache_ttl_clamped_to_maximum(self, mock_get, _url_mock):
        metadata = _make_metadata()
        mock_get.return_value = _mock_response(metadata, headers={"Cache-Control": "max-age=999999"})
        _, ttl = fetch_cimd_metadata(VALID_CIMD_URL)
        self.assertEqual(ttl, 86400)  # Clamped to 24h maximum

    @patch("posthog.api.oauth.cimd.requests.Session.get")
    def test_default_cache_ttl(self, mock_get, _url_mock):
        metadata = _make_metadata()
        mock_get.return_value = _mock_response(metadata, headers={})
        _, ttl = fetch_cimd_metadata(VALID_CIMD_URL)
        self.assertEqual(ttl, 3600)  # Default 1 hour


@patch("posthog.security.url_validation.resolve_host_ips", return_value={ip_address("93.184.216.34")})
class TestFetchAndUpsertCimdApplication(APIBaseTest):
    """Tests for fetch_and_upsert_cimd_application — the core fetch+create/update function."""

    @patch("posthog.api.oauth.cimd.requests.Session.get")
    def test_creates_new_application(self, mock_get, _url_mock):
        metadata = _make_metadata(logo_uri="https://example.com/logo.png")
        mock_get.return_value = _mock_response(metadata, headers={})

        app = fetch_and_upsert_cimd_application(VALID_CIMD_URL)

        self.assertIsNotNone(app)
        assert app is not None
        self.assertTrue(app.is_cimd_client)
        self.assertFalse(app.is_dcr_client)
        self.assertEqual(app.client_id, VALID_CIMD_URL)
        self.assertEqual(app.cimd_metadata_url, VALID_CIMD_URL)
        self.assertEqual(app.name, "Test MCP Client")
        self.assertEqual(app.redirect_uris, "http://127.0.0.1:3000/callback")
        self.assertEqual(app.logo_uri, "https://example.com/logo.png")
        self.assertIsNotNone(app.cimd_metadata_last_fetched)
        self.assertIsNone(app.organization)
        self.assertIsNone(app.user)

    @parameterized.expand(
        [
            # A registered partner publishing a key set is the upgrade path with no
            # re-onboarding: it edits its own metadata document and the next refresh promotes
            # it in place.
            (
                "partner_promoted_when_a_jwks_uri_appears",
                True,
                False,
                True,
                TokenEndpointAuthMethod.PRIVATE_KEY_JWT,
                CIMD_JWKS_URI,
            ),
            # A confidential partner whose key source disappeared could never authenticate
            # again, so it must fall back to public rather than becoming permanently unusable.
            ("partner_demoted_when_the_jwks_uri_disappears", True, True, False, TokenEndpointAuthMethod.NONE, None),
            # A client that never registered as a partner cannot promote its client_type by
            # editing a document it controls: it stays on the PKCE it was already relying on.
            # But the jwks_uri is still stored, so a presented assertion can be verified —
            # the declaration only ever raises what we accept, never what we require.
            (
                "non_partner_stores_jwks_uri_without_promotion",
                False,
                False,
                True,
                TokenEndpointAuthMethod.NONE,
                CIMD_JWKS_URI,
            ),
        ]
    )
    @patch("posthog.api.oauth.cimd.requests.Session.get")
    def test_client_authentication_is_re_derived_on_every_refresh(
        self,
        _name,
        is_partner,
        starts_with_jwks,
        ends_with_jwks,
        expected_method,
        expected_jwks_uri,
        mock_get,
        _url_mock,
    ):
        mock_get.return_value = _mock_response(_metadata_for_auth(starts_with_jwks), headers={})
        app = fetch_and_upsert_cimd_application(VALID_CIMD_URL, allow_confidential=is_partner)
        assert app is not None
        if is_partner:
            app = apply_provisioning_defaults(app)

        mock_get.return_value = _mock_response(_metadata_for_auth(ends_with_jwks), headers={})
        refreshed = fetch_and_upsert_cimd_application(VALID_CIMD_URL)

        assert refreshed is not None
        # Same row and same client_id: the transition needs no operator and no re-registration.
        self.assertEqual(refreshed.pk, app.pk)
        self.assertEqual(refreshed.client_id, app.client_id)
        self.assertIs(refreshed.token_endpoint_auth_method, expected_method)
        self.assertEqual(refreshed.jwks_uri, expected_jwks_uri)
        if expected_method is TokenEndpointAuthMethod.PRIVATE_KEY_JWT:
            # It holds no secret, but it can authenticate, so it is confidential per RFC 6749.
            self.assertEqual(refreshed.client_type, OAuthApplication.CLIENT_CONFIDENTIAL)
        else:
            self.assertEqual(refreshed.client_type, OAuthApplication.CLIENT_PUBLIC)

    @patch("posthog.api.oauth.cimd.requests.Session.get")
    def test_updates_existing_application(self, mock_get, _url_mock):
        metadata1 = _make_metadata(client_name="Original Name")
        mock_get.return_value = _mock_response(metadata1, headers={})
        app = fetch_and_upsert_cimd_application(VALID_CIMD_URL)
        assert app is not None

        metadata2 = _make_metadata(client_name="Updated Name", logo_uri="https://example.com/new-logo.png")
        mock_get.return_value = _mock_response(metadata2, headers={})
        updated = fetch_and_upsert_cimd_application(VALID_CIMD_URL)

        assert updated is not None
        self.assertEqual(updated.pk, app.pk)
        self.assertEqual(updated.name, "Updated Name")
        self.assertEqual(updated.logo_uri, "https://example.com/new-logo.png")

    @patch("posthog.api.oauth.cimd.requests.Session.get")
    def test_returns_none_when_lock_held(self, mock_get, _url_mock):
        # Simulate another caller holding the lock
        real_cache.set(_fetch_lock_key(VALID_CIMD_URL), True, timeout=30)

        result = fetch_and_upsert_cimd_application(VALID_CIMD_URL)
        self.assertIsNone(result)
        self.assertEqual(_document_fetches(mock_get), [])

        real_cache.delete(_fetch_lock_key(VALID_CIMD_URL))

    @patch("posthog.api.oauth.cimd.requests.Session.get")
    def test_blocked_name_uses_default(self, mock_get, _url_mock):
        metadata = _make_metadata(client_name="PostHog Official Client")
        mock_get.return_value = _mock_response(metadata, headers={})

        app = fetch_and_upsert_cimd_application(VALID_CIMD_URL)
        assert app is not None
        self.assertEqual(app.name, "CIMD Client")

    @patch("posthog.api.oauth.cimd.requests.Session.get")
    def test_fetch_failure_propagates(self, mock_get, _url_mock):
        mock_get.side_effect = requests.ConnectionError("DNS resolution failed")
        with self.assertRaises(CIMDFetchError):
            fetch_and_upsert_cimd_application(VALID_CIMD_URL)

    @patch("posthog.api.oauth.cimd.requests.Session.get")
    def test_blocked_url_prevents_fetch(self, mock_get, _url_mock):
        from posthog.api.oauth.cimd import block_cimd_url, unblock_cimd_url

        block_cimd_url(VALID_CIMD_URL)
        result = fetch_and_upsert_cimd_application(VALID_CIMD_URL)
        self.assertIsNone(result)
        self.assertEqual(_document_fetches(mock_get), [])

        unblock_cimd_url(VALID_CIMD_URL)

    @patch("posthog.api.oauth.cimd.requests.Session.get")
    def test_releases_lock_on_failure(self, mock_get, _url_mock):
        mock_get.side_effect = requests.ConnectionError("DNS failed")
        with self.assertRaises(CIMDFetchError):
            fetch_and_upsert_cimd_application(VALID_CIMD_URL)

        # Lock should be released — a subsequent call should acquire it
        self.assertIsNone(real_cache.get(_fetch_lock_key(VALID_CIMD_URL)))


@patch("posthog.security.url_validation.resolve_host_ips", return_value={ip_address("93.184.216.34")})
class TestGetOrCreateCimdApplication(APIBaseTest):
    """Tests for get_or_create_cimd_application — the orchestration layer."""

    @patch("posthog.api.oauth.cimd.requests.Session.get")
    def test_returns_existing_when_cache_fresh(self, mock_get, _url_mock):
        metadata = _make_metadata()
        mock_get.return_value = _mock_response(metadata, headers={})

        app1 = get_or_create_cimd_application(VALID_CIMD_URL)
        app2 = get_or_create_cimd_application(VALID_CIMD_URL)

        self.assertEqual(app1.pk, app2.pk)
        self.assertEqual(len(_document_fetches(mock_get)), 1)

    @patch("posthog.api.oauth.cimd.cache")
    @patch("posthog.api.oauth.cimd.requests.Session.get")
    def test_stale_cache_returns_immediately_and_queues_refresh(self, mock_get, mock_cache, _url_mock):
        mock_cache.get.return_value = None
        mock_cache.add.return_value = True
        metadata = _make_metadata(client_name="Original Name")
        mock_get.return_value = _mock_response(metadata, headers={})
        app = get_or_create_cimd_application(VALID_CIMD_URL)

        with patch("posthog.api.oauth.cimd.refresh_cimd_metadata_task") as mock_task:
            result = get_or_create_cimd_application(VALID_CIMD_URL)
            self.assertEqual(result.pk, app.pk)
            self.assertEqual(result.name, "Original Name")
            mock_task.delay.assert_called_once_with(VALID_CIMD_URL)

    def test_stale_refresh_enqueues_one_task_while_pending(self, _url_mock):
        real_cache.clear()
        # The staleness check runs before any client authentication, so a burst of requests
        # against a stale document must coalesce into one queued task, not one per request.
        with patch("posthog.api.oauth.cimd.refresh_cimd_metadata_task") as mock_task:
            enqueue_cimd_refresh_if_stale(VALID_CIMD_URL)
            enqueue_cimd_refresh_if_stale(VALID_CIMD_URL)
            mock_task.delay.assert_called_once_with(VALID_CIMD_URL)

    @patch("posthog.api.oauth.cimd.requests.Session.get")
    def test_new_client_fetch_failure_raises(self, mock_get, _url_mock):
        mock_get.side_effect = requests.ConnectionError("DNS resolution failed")
        with self.assertRaises(CIMDFetchError):
            get_or_create_cimd_application(VALID_CIMD_URL)

    @patch("posthog.api.oauth.cimd.requests.Session.get")
    def test_refresh_task_updates_metadata(self, mock_get, _url_mock):
        metadata1 = _make_metadata(client_name="Original Name")
        mock_get.return_value = _mock_response(metadata1, headers={})
        fetch_and_upsert_cimd_application(VALID_CIMD_URL)

        metadata2 = _make_metadata(client_name="Updated Name", logo_uri="https://example.com/new-logo.png")
        mock_get.return_value = _mock_response(metadata2, headers={})
        refresh_cimd_metadata_task(VALID_CIMD_URL)

        app = OAuthApplication.objects.get(client_id=VALID_CIMD_URL)
        self.assertEqual(app.name, "Updated Name")
        self.assertEqual(app.logo_uri, "https://example.com/new-logo.png")

    @parameterized.expand(
        [
            ("script_tag", "<script>alert(1)</script>"),
            ("attribute_breakout", '"><img src=x onerror=alert(1)>'),
            ("ampersand_preserved", "Acme & Co"),
            ("over_length_after_escape", "<" * 300),
        ]
    )
    @patch("posthog.api.oauth.cimd.requests.Session.get")
    def test_client_name_from_metadata_is_html_escaped(self, _name, payload, mock_get, _url_mock):
        mock_get.return_value = _mock_response(_make_metadata(client_name=payload), headers={})

        app = fetch_and_upsert_cimd_application(VALID_CIMD_URL)

        assert app is not None
        expected = sanitize_client_name(payload)
        self.assertEqual(app.name, expected)
        self.assertNotIn("<", app.name)
        self.assertNotIn(">", app.name)

    @patch("posthog.api.oauth.cimd.requests.Session.get")
    def test_refresh_escapes_client_name_idempotently(self, mock_get, _url_mock):
        payload = "<script>alert(1)</script>"
        mock_get.return_value = _mock_response(_make_metadata(client_name="Safe Name"), headers={})
        fetch_and_upsert_cimd_application(VALID_CIMD_URL)

        # Refresh twice with the same script payload — each call needs its own response because
        # _mock_response's iter_content is a one-shot iterator. Re-escaping the raw metadata each
        # time must not compound (it escapes the metadata value, not the already-escaped app.name).
        for _ in range(2):
            mock_get.return_value = _mock_response(_make_metadata(client_name=payload), headers={})
            refresh_cimd_metadata_task(VALID_CIMD_URL)

        app = OAuthApplication.objects.get(client_id=VALID_CIMD_URL)
        self.assertEqual(app.name, escape(payload))
        self.assertNotIn("<", app.name)

    @patch("posthog.api.oauth.cimd.requests.Session.get")
    def test_refresh_task_handles_fetch_failure_gracefully(self, mock_get, _url_mock):
        metadata = _make_metadata(client_name="Original Name")
        mock_get.return_value = _mock_response(metadata, headers={})
        fetch_and_upsert_cimd_application(VALID_CIMD_URL)

        mock_get.side_effect = requests.ConnectionError("DNS failed")
        refresh_cimd_metadata_task(VALID_CIMD_URL)

        app = OAuthApplication.objects.get(client_id=VALID_CIMD_URL)
        self.assertEqual(app.name, "Original Name")

    @patch("posthog.api.oauth.cimd.capture_exception")
    @patch("posthog.api.oauth.cimd.fetch_and_upsert_cimd_application")
    def test_refresh_task_does_not_capture_expected_validation_error(self, mock_fetch, mock_capture, _url_mock):
        # Rejecting a non-compliant partner document is expected, so it must not surface as an error-tracking issue.
        mock_fetch.side_effect = CIMDValidationError("document exceeds the 5120 byte limit")
        refresh_cimd_metadata_task(VALID_CIMD_URL)
        mock_capture.assert_not_called()

    @patch("posthog.api.oauth.cimd.capture_exception")
    @patch("posthog.api.oauth.cimd.fetch_and_upsert_cimd_application")
    def test_refresh_task_captures_unexpected_fetch_error(self, mock_fetch, mock_capture, _url_mock):
        error = CIMDFetchError("connection reset")
        mock_fetch.side_effect = error
        refresh_cimd_metadata_task(VALID_CIMD_URL)
        mock_capture.assert_called_once_with(error)


@patch("posthog.security.url_validation.resolve_host_ips", return_value={ip_address("93.184.216.34")})
class TestApplyProvisioningDefaults(APIBaseTest):
    @patch("posthog.api.oauth.cimd.requests.Session.get")
    def test_opting_a_cimd_app_in_grants_the_full_default_profile(self, mock_get, _url_mock):
        mock_get.return_value = _mock_response(_make_metadata(), headers={})
        existing = fetch_and_upsert_cimd_application(VALID_CIMD_URL)
        assert existing is not None
        self.assertFalse(existing.is_provisioning_partner)

        app = apply_provisioning_defaults(existing)

        self.assertTrue(app.is_provisioning_partner)
        self.assertTrue(app.provisioning.active)
        self.assertTrue(app.provisioning.can_create_accounts)
        self.assertTrue(app.provisioning.can_provision_resources)
        # No limits are persisted at registration: budgets derive from the tier.
        self.assertEqual(app.provisioning.rate_limits, {})

    @parameterized.expand(
        [
            ("registration_call", True, True),
            # The /authorize and background-refresh paths read the same document. Promoting
            # there would grant the capabilities outside the registration endpoint, so past its
            # per-client_id, per-IP and per-domain throttles, and on a request the client did
            # not make.
            ("ordinary_fetch", False, False),
        ]
    )
    @patch("posthog.api.oauth.cimd.requests.Session.get")
    def test_only_the_registration_call_promotes_a_declaring_document(
        self, _name, register_provisioning, expected_partner, mock_get, _url_mock
    ):
        mock_get.return_value = _mock_response(_make_metadata(com_posthog={"provisioning": True}), headers={})

        app = fetch_and_upsert_cimd_application(VALID_CIMD_URL, register_provisioning=register_provisioning)

        assert app is not None
        self.assertEqual(app.is_provisioning_partner, expected_partner)
        self.assertEqual(app.provisioning.can_create_accounts, expected_partner)

    @patch("posthog.api.oauth.cimd.posthoganalytics.capture")
    @patch("posthog.api.oauth.cimd.requests.Session.get")
    def test_registration_event_fires_once_on_the_transition(self, mock_get, mock_capture, _url_mock):
        mock_get.return_value = _mock_response(_make_metadata(), headers={})
        existing = fetch_and_upsert_cimd_application(VALID_CIMD_URL)
        assert existing is not None

        apply_provisioning_defaults(existing)
        self.assertIn("cimd_provisioning_partner_registered", _captured_events(mock_capture))

        mock_capture.reset_mock()
        apply_provisioning_defaults(existing)
        self.assertNotIn("cimd_provisioning_partner_registered", _captured_events(mock_capture))

    @patch("posthog.api.oauth.cimd.posthoganalytics.capture")
    @patch("posthog.api.oauth.cimd.requests.Session.get")
    def test_disabled_partner_is_not_re_enabled(self, mock_get, mock_capture, _url_mock):
        mock_get.return_value = _mock_response(_make_metadata(), headers={})
        existing = fetch_and_upsert_cimd_application(VALID_CIMD_URL)
        assert existing is not None
        # Disabled through a separate row read, so `existing` still holds the pre-revocation
        # copy - the state a registration is in when its metadata fetch overlaps an admin edit.
        OAuthApplication.objects.get(pk=existing.pk).update_provisioning(disabled=True)
        mock_capture.reset_mock()

        app = apply_provisioning_defaults(existing)

        self.assertFalse(app.is_provisioning_partner)
        app.refresh_from_db()
        self.assertFalse(app.is_provisioning_partner)
        self.assertNotIn("cimd_provisioning_partner_registered", _captured_events(mock_capture))

    @patch("posthog.api.oauth.cimd.requests.Session.get")
    def test_registration_does_not_overwrite_a_partner_created_mid_fetch(self, mock_get, _url_mock):
        mock_get.return_value = _mock_response(_make_metadata(), headers={})
        existing = fetch_and_upsert_cimd_application(VALID_CIMD_URL)
        assert existing is not None
        # An admin registers and restricts the client through a separate row read, the way it
        # looks to a registration whose metadata fetch overlapped the edit. `existing` still
        # says non-partner, so only the locked read can tell the defaults not to land.
        admin_copy = OAuthApplication.objects.get(pk=existing.pk)
        admin_copy.is_provisioning_partner = True
        admin_copy.save(update_fields=["is_provisioning_partner"])
        admin_copy.update_provisioning(active=False, can_create_accounts=False)

        app = apply_provisioning_defaults(existing)

        app.refresh_from_db()
        self.assertFalse(app.provisioning.active)
        self.assertFalse(app.provisioning.can_create_accounts)

    @patch("posthog.api.oauth.cimd.requests.Session.get")
    def test_registration_does_not_restore_a_capability_revoked_mid_fetch(self, mock_get, _url_mock):
        mock_get.return_value = _mock_response(_make_metadata(), headers={})
        existing = fetch_and_upsert_cimd_application(VALID_CIMD_URL)
        assert existing is not None
        existing.update_provisioning(can_use_github_grants=True)
        OAuthApplication.objects.get(pk=existing.pk).update_provisioning(can_use_github_grants=False)

        app = apply_provisioning_defaults(existing)

        self.assertFalse(app.provisioning.can_use_github_grants)
        app.refresh_from_db()
        self.assertFalse(app.provisioning.can_use_github_grants)
        # The self-serve defaults still land - only the admin's revocation survives on top.
        self.assertTrue(app.provisioning.can_create_accounts)


@patch("posthog.security.url_validation.resolve_host_ips", return_value={ip_address("93.184.216.34")})
class TestCIMDVerificationToken(APIBaseTest):
    @patch("posthog.api.oauth.cimd.requests.Session.get")
    def test_valid_verification_token_links_app_to_organization(self, mock_get, _url_mock):
        token, plaintext = create_cimd_verification_token(
            organization=self.organization, label="Test partner", cimd_url=VALID_CIMD_URL, created_by=self.user
        )
        metadata = _make_metadata(posthog_verification_token=plaintext)
        mock_get.return_value = _mock_response(metadata, headers={})

        app = fetch_and_upsert_cimd_application(VALID_CIMD_URL)

        assert app is not None
        self.assertEqual(app.organization_id, self.organization.id)
        token.refresh_from_db()
        self.assertIsNotNone(token.last_used_at)

    @patch("posthog.api.oauth.cimd.requests.Session.get")
    def test_invalid_verification_token_leaves_app_unlinked(self, mock_get, _url_mock):
        metadata = _make_metadata(posthog_verification_token="phvt_totally_made_up")
        mock_get.return_value = _mock_response(metadata, headers={})

        app = fetch_and_upsert_cimd_application(VALID_CIMD_URL)

        assert app is not None
        self.assertIsNone(app.organization_id)

    @patch("posthog.api.oauth.cimd.requests.Session.get")
    def test_missing_verification_token_leaves_app_unlinked(self, mock_get, _url_mock):
        mock_get.return_value = _mock_response(_make_metadata(), headers={})

        app = fetch_and_upsert_cimd_application(VALID_CIMD_URL)

        assert app is not None
        self.assertIsNone(app.organization_id)

    @patch("posthog.api.oauth.cimd.requests.Session.get")
    def test_verified_partner_derives_the_attested_tier(self, mock_get, _url_mock):
        _, plaintext = create_cimd_verification_token(
            organization=self.organization, label="Verified partner", cimd_url=VALID_CIMD_URL, created_by=self.user
        )
        metadata = _make_metadata(posthog_verification_token=plaintext)
        mock_get.return_value = _mock_response(metadata, headers={})

        app = _register_provisioning_partner()

        assert app is not None
        self.assertEqual(app.organization_id, self.organization.id)
        self.assertEqual(app.partner_tier, PartnerTier.PUBLIC_ATTESTED)
        self.assertEqual(app.provisioning.rate_limits, {})

    @patch("posthog.api.oauth.cimd.requests.Session.get")
    def test_unverified_partner_derives_the_public_tier(self, mock_get, _url_mock):
        mock_get.return_value = _mock_response(_make_metadata(), headers={})

        app = _register_provisioning_partner()

        assert app is not None
        self.assertIsNone(app.organization_id)
        self.assertEqual(app.partner_tier, PartnerTier.PUBLIC)
        self.assertEqual(app.provisioning.rate_limits, {})

    @patch("posthog.api.oauth.cimd.requests.Session.get")
    def test_refresh_unlinks_app_when_token_removed(self, mock_get, _url_mock):
        _, plaintext = create_cimd_verification_token(
            organization=self.organization, label="Rotating partner", cimd_url=VALID_CIMD_URL, created_by=self.user
        )
        # First fetch: with token → linked
        mock_get.return_value = _mock_response(_make_metadata(posthog_verification_token=plaintext), headers={})
        app = fetch_and_upsert_cimd_application(VALID_CIMD_URL)
        assert app is not None
        self.assertEqual(app.organization_id, self.organization.id)

        # Second fetch: metadata no longer contains the token → must unlink
        real_cache.delete(_fetch_lock_key(VALID_CIMD_URL))
        mock_get.return_value = _mock_response(_make_metadata(), headers={})
        refreshed = fetch_and_upsert_cimd_application(VALID_CIMD_URL)
        assert refreshed is not None
        self.assertIsNone(refreshed.organization_id)

    @patch("posthog.api.oauth.cimd.requests.Session.get")
    def test_refresh_links_app_when_token_added(self, mock_get, _url_mock):
        # First fetch: no token → unlinked
        mock_get.return_value = _mock_response(_make_metadata(), headers={})
        app = fetch_and_upsert_cimd_application(VALID_CIMD_URL)
        assert app is not None
        self.assertIsNone(app.organization_id)

        # Partner adds a token and we refetch
        _, plaintext = create_cimd_verification_token(
            organization=self.organization, label="Added later", cimd_url=VALID_CIMD_URL, created_by=self.user
        )
        real_cache.delete(_fetch_lock_key(VALID_CIMD_URL))
        mock_get.return_value = _mock_response(_make_metadata(posthog_verification_token=plaintext), headers={})
        refreshed = fetch_and_upsert_cimd_application(VALID_CIMD_URL)
        assert refreshed is not None
        self.assertEqual(refreshed.organization_id, self.organization.id)

    @patch("posthog.api.oauth.cimd.requests.Session.get")
    def test_non_string_verification_token_is_ignored(self, mock_get, _url_mock):
        metadata = _make_metadata()
        metadata["posthog_verification_token"] = {"not": "a string"}
        mock_get.return_value = _mock_response(metadata, headers={})

        app = fetch_and_upsert_cimd_application(VALID_CIMD_URL)

        assert app is not None
        self.assertIsNone(app.organization_id)

    @patch("posthog.api.oauth.cimd.requests.Session.get")
    def test_refresh_moves_the_tier_when_token_added_post_registration(self, mock_get, _url_mock):
        mock_get.return_value = _mock_response(_make_metadata(), headers={})
        _register_provisioning_partner()
        app = OAuthApplication.objects.get(client_id=VALID_CIMD_URL)
        self.assertIsNone(app.organization_id)
        self.assertEqual(app.partner_tier, PartnerTier.PUBLIC)

        _, plaintext = create_cimd_verification_token(
            organization=self.organization,
            label="Added post-registration",
            cimd_url=VALID_CIMD_URL,
            created_by=self.user,
        )
        real_cache.delete(_fetch_lock_key(VALID_CIMD_URL))
        mock_get.return_value = _mock_response(_make_metadata(posthog_verification_token=plaintext), headers={})
        refreshed = fetch_and_upsert_cimd_application(VALID_CIMD_URL)

        assert refreshed is not None
        self.assertEqual(refreshed.organization_id, self.organization.id)
        self.assertEqual(refreshed.partner_tier, PartnerTier.PUBLIC_ATTESTED)
        self.assertEqual(refreshed.provisioning.rate_limits, {})

    @patch("posthog.api.oauth.cimd.requests.Session.get")
    def test_refresh_moves_the_tier_back_when_token_removed(self, mock_get, _url_mock):
        _, plaintext = create_cimd_verification_token(
            organization=self.organization, label="Rotating partner", cimd_url=VALID_CIMD_URL, created_by=self.user
        )
        mock_get.return_value = _mock_response(_make_metadata(posthog_verification_token=plaintext), headers={})
        _register_provisioning_partner()
        app = OAuthApplication.objects.get(client_id=VALID_CIMD_URL)
        self.assertEqual(app.organization_id, self.organization.id)
        self.assertEqual(app.partner_tier, PartnerTier.PUBLIC_ATTESTED)

        real_cache.delete(_fetch_lock_key(VALID_CIMD_URL))
        mock_get.return_value = _mock_response(_make_metadata(), headers={})
        refreshed = fetch_and_upsert_cimd_application(VALID_CIMD_URL)

        assert refreshed is not None
        self.assertIsNone(refreshed.organization_id)
        self.assertEqual(refreshed.partner_tier, PartnerTier.PUBLIC)

    @patch("posthog.api.oauth.cimd.requests.Session.get")
    def test_refresh_preserves_admin_custom_rate_limit(self, mock_get, _url_mock):
        mock_get.return_value = _mock_response(_make_metadata(), headers={})
        _register_provisioning_partner()
        app = OAuthApplication.objects.get(client_id=VALID_CIMD_URL)
        app.update_provisioning_rate_limits(account_requests=250)
        _, plaintext = create_cimd_verification_token(
            organization=self.organization, label="Post-admin-override", cimd_url=VALID_CIMD_URL, created_by=self.user
        )
        real_cache.delete(_fetch_lock_key(VALID_CIMD_URL))
        mock_get.return_value = _mock_response(_make_metadata(posthog_verification_token=plaintext), headers={})
        refreshed = fetch_and_upsert_cimd_application(VALID_CIMD_URL)

        assert refreshed is not None
        self.assertEqual(refreshed.organization_id, self.organization.id)
        self.assertEqual(refreshed.provisioning.rate_limits, {"account_requests": 250})


@patch("posthog.security.url_validation.resolve_host_ips", return_value={ip_address("93.184.216.34")})
class TestCIMDVerificationTokenURLBinding(APIBaseTest):
    """The metadata document is public, so the token in it can be read and republished
    by anyone. These lock in that the URL is what decides who the token belongs to."""

    @patch("posthog.api.oauth.cimd.requests.Session.get")
    def test_token_copied_to_another_url_does_not_link_the_app(self, mock_get, _url_mock):
        _, plaintext = create_cimd_verification_token(
            organization=self.organization, label="Victim", cimd_url=VALID_CIMD_URL, created_by=self.user
        )
        attacker_url = "https://attacker.example.com/.well-known/oauth-client-metadata.json"
        mock_get.return_value = _mock_response(
            _make_metadata(url=attacker_url, posthog_verification_token=plaintext), headers={}
        )

        app = fetch_and_upsert_cimd_application(attacker_url)

        assert app is not None
        self.assertIsNone(app.organization_id)

    @patch("posthog.api.oauth.cimd.requests.Session.get")
    def test_unbound_legacy_token_no_longer_verifies(self, mock_get, _url_mock):
        token, plaintext = create_cimd_verification_token(
            organization=self.organization, label="Legacy", cimd_url=VALID_CIMD_URL, created_by=self.user
        )
        token.cimd_url = None
        token.save(update_fields=["cimd_url"])
        mock_get.return_value = _mock_response(_make_metadata(posthog_verification_token=plaintext), headers={})

        app = fetch_and_upsert_cimd_application(VALID_CIMD_URL)

        assert app is not None
        self.assertIsNone(app.organization_id)

    @patch("posthog.api.oauth.cimd.requests.Session.get")
    def test_claiming_a_url_does_not_block_the_real_publisher(self, mock_get, _url_mock):
        # No uniqueness on cimd_url, so a squatter naming someone else's URL first
        # cannot lock them out — only the token actually served there verifies.
        squatter_org = Organization.objects.create(name="Squatter")
        create_cimd_verification_token(
            organization=squatter_org, label="Squat", cimd_url=VALID_CIMD_URL, created_by=None
        )
        _, plaintext = create_cimd_verification_token(
            organization=self.organization, label="Real partner", cimd_url=VALID_CIMD_URL, created_by=self.user
        )
        mock_get.return_value = _mock_response(_make_metadata(posthog_verification_token=plaintext), headers={})

        app = fetch_and_upsert_cimd_application(VALID_CIMD_URL)

        assert app is not None
        self.assertEqual(app.organization_id, self.organization.id)

    @parameterized.expand(
        [
            ("trailing_slash", VALID_CIMD_URL + "/"),
            ("uppercase_host", "https://APP.EXAMPLE.COM/.well-known/oauth-client-metadata.json"),
            ("explicit_default_port", "https://app.example.com:443/.well-known/oauth-client-metadata.json"),
        ]
    )
    @patch("posthog.api.oauth.cimd.requests.Session.get")
    def test_equivalent_url_spellings_still_verify(self, _name, issued_url, mock_get, _url_mock):
        _, plaintext = create_cimd_verification_token(
            organization=self.organization, label="Partner", cimd_url=issued_url, created_by=self.user
        )
        mock_get.return_value = _mock_response(_make_metadata(posthog_verification_token=plaintext), headers={})

        app = fetch_and_upsert_cimd_application(VALID_CIMD_URL)

        assert app is not None
        self.assertEqual(app.organization_id, self.organization.id)


@patch("posthog.security.url_validation.resolve_host_ips", return_value={ip_address("93.184.216.34")})
class TestCIMDVerificationRejectedCaptureEvent(APIBaseTest):
    """`_capture_verification_rejected` emits `cimd_verification_token_rejected`. These lock in:
    the event reaching an injected capture callable (so it isn't silently dropped in Celery),
    a stable non-attacker-controlled distinct_id, the per-(token, url, reason) dedup, and a
    distinct reason for an app with no metadata URL."""

    def setUp(self):
        super().setUp()
        real_cache.clear()

    @patch("posthog.api.oauth.cimd.requests.Session.get")
    def test_rejection_fires_through_injected_capture_on_refresh(self, mock_get, _url_mock):
        other_url = "https://other.example.com/.well-known/oauth-client-metadata.json"
        _, plaintext = create_cimd_verification_token(
            organization=self.organization, label="Victim", cimd_url=other_url, created_by=self.user
        )
        mock_get.return_value = _mock_response(_make_metadata(), headers={})
        app = fetch_and_upsert_cimd_application(VALID_CIMD_URL)
        assert app is not None

        # The copied-token rejection only triggers on refresh, since a first fetch has no
        # existing app to compare against — this is the path a bare posthoganalytics.capture
        # silently drops in Celery.
        real_cache.delete(_fetch_lock_key(VALID_CIMD_URL))
        mock_capture = MagicMock()
        mock_get.return_value = _mock_response(_make_metadata(posthog_verification_token=plaintext), headers={})
        refreshed = fetch_and_upsert_cimd_application(VALID_CIMD_URL, capture_ph_event=mock_capture)

        assert refreshed is not None
        rejected = [
            call
            for call in mock_capture.call_args_list
            if call.kwargs.get("event") == "cimd_verification_token_rejected"
        ]
        self.assertEqual(len(rejected), 1)
        self.assertEqual(rejected[0].kwargs["properties"]["reason"], "url_mismatch")

    @patch("posthog.api.oauth.cimd.requests.Session.get")
    def test_rejection_distinct_id_is_organization_not_url(self, mock_get, _url_mock):
        token, plaintext = create_cimd_verification_token(
            organization=self.organization, label="Legacy", cimd_url=VALID_CIMD_URL, created_by=self.user
        )
        token.cimd_url = None
        token.save(update_fields=["cimd_url"])
        mock_get.return_value = _mock_response(_make_metadata(posthog_verification_token=plaintext), headers={})
        mock_capture = MagicMock()

        app = fetch_and_upsert_cimd_application(VALID_CIMD_URL, capture_ph_event=mock_capture)

        assert app is not None
        rejected = [
            call
            for call in mock_capture.call_args_list
            if call.kwargs.get("event") == "cimd_verification_token_rejected"
        ]
        self.assertEqual(len(rejected), 1)
        self.assertEqual(rejected[0].kwargs["distinct_id"], str(self.organization.id))

    @patch("posthog.api.oauth.cimd.requests.Session.get")
    def test_rejection_deduped_for_same_token_url_reason(self, mock_get, _url_mock):
        token, plaintext = create_cimd_verification_token(
            organization=self.organization, label="Legacy", cimd_url=VALID_CIMD_URL, created_by=self.user
        )
        token.cimd_url = None
        token.save(update_fields=["cimd_url"])
        metadata = _make_metadata(posthog_verification_token=plaintext)
        mock_capture = MagicMock()

        mock_get.return_value = _mock_response(metadata, headers={})
        fetch_and_upsert_cimd_application(VALID_CIMD_URL, capture_ph_event=mock_capture)

        real_cache.delete(_fetch_lock_key(VALID_CIMD_URL))
        mock_get.return_value = _mock_response(metadata, headers={})
        fetch_and_upsert_cimd_application(VALID_CIMD_URL, capture_ph_event=mock_capture)

        rejected = [
            call
            for call in mock_capture.call_args_list
            if call.kwargs.get("event") == "cimd_verification_token_rejected"
        ]
        self.assertEqual(len(rejected), 1)

    def test_missing_app_url_rejects_as_app_url_missing_not_mismatch(self, _url_mock):
        # url_mismatch is the copied-token signal, so a resolution with no URL to compare
        # against has to report its own reason instead of landing in that metric.
        _, plaintext = create_cimd_verification_token(
            organization=self.organization, label="Bound", cimd_url=VALID_CIMD_URL, created_by=self.user
        )
        mock_capture = MagicMock()

        resolved = _resolve_verification_token(
            cast(CIMDMetadataDocument, _make_metadata(posthog_verification_token=plaintext)),
            "",
            capture_ph_event=mock_capture,
        )

        self.assertIsNone(resolved)
        rejected = [
            call
            for call in mock_capture.call_args_list
            if call.kwargs.get("event") == "cimd_verification_token_rejected"
        ]
        self.assertEqual(len(rejected), 1)
        self.assertEqual(rejected[0].kwargs["properties"]["reason"], "app_url_missing")


class TestAuthorizationServerMetadata(APIBaseTest):
    def test_advertises_cimd_support(self):
        client = APIClient()
        response = client.get("/.well-known/oauth-authorization-server")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data.get("client_id_metadata_document_supported"))


@patch("posthog.security.url_validation.resolve_host_ips", return_value={ip_address("93.184.216.34")})
class TestCIMDAuthorizeIntegration(APIBaseTest):
    """Integration tests for the CIMD flow through /oauth/authorize/."""

    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)
        self.code_verifier = "test_verifier_string"

    @property
    def code_challenge(self) -> str:
        digest = hashlib.sha256(self.code_verifier.encode()).digest()
        return base64.urlsafe_b64encode(digest).decode().replace("=", "")

    def _authorize_url(self, client_id: str, redirect_uri: str = "http://127.0.0.1:3000/callback") -> str:
        params = urlencode(
            {
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "code_challenge": self.code_challenge,
                "code_challenge_method": "S256",
            }
        )
        return f"/oauth/authorize/?{params}"

    @patch("posthog.api.oauth.cimd.requests.Session.get")
    def test_cimd_url_creates_app_and_returns_consent_screen(self, mock_get, _url_mock):
        metadata = _make_metadata()
        mock_get.return_value = _mock_response(metadata)
        url = self._authorize_url(VALID_CIMD_URL)

        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        app = OAuthApplication.objects.get(client_id=VALID_CIMD_URL)
        self.assertTrue(app.is_cimd_client)
        self.assertEqual(app.name, "Test MCP Client")
        self.assertEqual(len(_document_fetches(mock_get)), 1)

    @patch("posthog.api.oauth.cimd.requests.Session.get")
    def test_cimd_existing_app_skips_fetch(self, mock_get, _url_mock):
        # Pre-create a CIMD app
        metadata = _make_metadata()
        mock_get.return_value = _mock_response(metadata)
        url = self._authorize_url(VALID_CIMD_URL)
        self.client.get(url)
        mock_get.reset_mock()

        # Second request should hit cache in get_or_create, no outbound fetch
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(_document_fetches(mock_get), [])
        self.assertEqual(OAuthApplication.objects.filter(client_id=VALID_CIMD_URL).count(), 1)

    @patch("posthog.api.oauth.cimd.requests.Session.get")
    def test_cimd_fetch_failure_rejects_new_client(self, mock_get, _url_mock):
        mock_get.side_effect = requests.ConnectionError("DNS failed")
        url = self._authorize_url(VALID_CIMD_URL)

        response = self.client.get(url)

        self.assertEqual(response.status_code, 400)
        self.assertIn("invalid", response.json().get("error", "").lower())

    @patch("posthog.api.oauth.cimd.requests.Session.get")
    def test_cimd_mismatched_redirect_uri_rejected(self, mock_get, _url_mock):
        metadata = _make_metadata()
        mock_get.return_value = _mock_response(metadata)
        # Use a redirect_uri not in the CIMD metadata
        url = self._authorize_url(VALID_CIMD_URL, redirect_uri="https://evil.com/steal")

        response = self.client.get(url)

        self.assertEqual(response.status_code, 400)

    @patch("posthog.api.oauth.cimd.requests.Session.get")
    def test_cimd_rate_limit_rejects_new_client(self, mock_get, _url_mock):
        metadata = _make_metadata()
        mock_get.return_value = _mock_response(metadata)

        mock_throttle = MagicMock()
        mock_throttle.allow_request.return_value = False
        mock_throttle.wait.return_value = 30
        mock_throttle.scope = "cimd_burst"
        mock_throttle_cls = MagicMock(return_value=mock_throttle)
        with patch("posthog.api.oauth.views.CIMD_THROTTLE_CLASSES", new=[mock_throttle_cls]):
            url = self._authorize_url("https://new-client.example.com/.well-known/oauth-client-metadata.json")
            response = self.client.get(url)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            _document_fetches(mock_get, "https://new-client.example.com/.well-known/oauth-client-metadata.json"), []
        )

    def test_cimd_requires_authentication(self, _url_mock):
        self.client.logout()
        url = self._authorize_url(VALID_CIMD_URL)

        response = self.client.get(url)

        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response["Location"])

    def _complete_pkce_flow(self, client_id: str):
        """Register the CIMD client (bypassing the consent-screen render, which needs a built
        frontend bundle this test has no reason to depend on), then drive /oauth/authorize/ to
        consent and /oauth/token/ to exchange the code, with no client credential."""
        get_or_create_cimd_application(client_id)
        consent = self.client.post(
            "/oauth/authorize/",
            {
                "client_id": client_id,
                "redirect_uri": "http://127.0.0.1:3000/callback",
                "response_type": "code",
                "code_challenge": self.code_challenge,
                "code_challenge_method": "S256",
                "allow": True,
                "access_level": OAuthApplicationAccessLevel.ALL.value,
                "scoped_organizations": [],
                "scoped_teams": [],
                "scope": "openid",
            },
        )
        code = consent.json()["redirect_to"].split("code=")[1].split("&")[0]
        return self.client.post(
            "/oauth/token/",
            {
                "grant_type": "authorization_code",
                "code": code,
                "client_id": client_id,
                "redirect_uri": "http://127.0.0.1:3000/callback",
                "code_verifier": self.code_verifier,
            },
        )

    @patch("posthog.api.oauth.cimd.requests.Session.get")
    def test_non_partner_cimd_client_declaring_private_key_jwt_authenticates_via_pkce(self, mock_get, _url_mock):
        # A CIMD client that has never registered as a provisioning partner cannot make itself
        # confidential just by declaring private_key_jwt in the document it controls, so it
        # must still be able to complete the ordinary public-client PKCE exchange.
        mock_get.return_value = _mock_response(_metadata_for_auth(with_jwks=True))

        token_response = self._complete_pkce_flow(VALID_CIMD_URL)

        self.assertEqual(token_response.status_code, 200, token_response.json())
        self.assertIn("access_token", token_response.json())
        app = OAuthApplication.objects.get(client_id=VALID_CIMD_URL)
        self.assertEqual(app.client_type, OAuthApplication.CLIENT_PUBLIC)
        # The jwks_uri is still stored, even though it did not promote client_type: if this
        # client starts signing, the token endpoint can verify it.
        self.assertEqual(app.jwks_uri, CIMD_JWKS_URI)

    @patch("posthog.api.oauth.cimd.requests.Session.get")
    def test_existing_non_partner_cimd_client_keeps_authenticating_after_document_flips(self, mock_get, _url_mock):
        # Reproduces the failure this gate exists to prevent: a working public client edits its
        # own metadata document after the fact, an unrelated background refresh picks that up,
        # and the client must still be able to authenticate afterwards.
        mock_get.return_value = _mock_response(_make_metadata())
        app = get_or_create_cimd_application(VALID_CIMD_URL)
        self.assertEqual(app.client_type, OAuthApplication.CLIENT_PUBLIC)

        mock_get.return_value = _mock_response(_metadata_for_auth(with_jwks=True))
        fetch_and_upsert_cimd_application(VALID_CIMD_URL)

        token_response = self._complete_pkce_flow(VALID_CIMD_URL)

        self.assertEqual(token_response.status_code, 200, token_response.json())
        self.assertIn("access_token", token_response.json())
        app.refresh_from_db()
        self.assertEqual(app.client_type, OAuthApplication.CLIENT_PUBLIC)


@patch("posthog.security.url_validation.resolve_host_ips", return_value={ip_address("93.184.216.34")})
class TestCIMDComPostHogNamespace(APIBaseTest):
    """Tests for the com.posthog namespace: scopes and nested verification_token."""

    # (d) dual-read: both com.posthog.verification_token and the legacy
    # posthog_verification_token must link the app to the organization.
    @parameterized.expand(
        [
            ("nested",),
            ("top_level",),
        ]
    )
    @patch("posthog.api.oauth.cimd.requests.Session.get")
    def test_verification_token_dual_read(self, token_placement, mock_get, _url_mock):
        token, plaintext = create_cimd_verification_token(
            organization=self.organization, label="Dual-read partner", cimd_url=VALID_CIMD_URL, created_by=self.user
        )
        if token_placement == "nested":
            metadata = _make_metadata(com_posthog={"verification_token": plaintext})
        else:
            metadata = _make_metadata(posthog_verification_token=plaintext)

        mock_get.return_value = _mock_response(metadata, headers={})
        app = fetch_and_upsert_cimd_application(VALID_CIMD_URL)

        assert app is not None
        self.assertEqual(app.organization_id, self.organization.id)

    # (d) continued: an unrecognized nested token falls back to a valid top-level one.
    @patch("posthog.api.oauth.cimd.requests.Session.get")
    def test_verification_token_falls_back_when_nested_unrecognized(self, mock_get, _url_mock):
        _, plaintext = create_cimd_verification_token(
            organization=self.organization, label="Fallback partner", cimd_url=VALID_CIMD_URL, created_by=self.user
        )
        metadata = _make_metadata(
            posthog_verification_token=plaintext,
            com_posthog={"verification_token": "phvt_does_not_exist"},
        )
        mock_get.return_value = _mock_response(metadata, headers={})
        app = fetch_and_upsert_cimd_application(VALID_CIMD_URL)

        assert app is not None
        self.assertEqual(app.organization_id, self.organization.id)

    # (d) continued: nested token takes precedence over top-level when both present.
    @patch("posthog.api.oauth.cimd.requests.Session.get")
    def test_nested_token_takes_precedence_over_top_level(self, mock_get, _url_mock):
        _, plaintext_nested = create_cimd_verification_token(
            organization=self.organization, label="Nested partner", cimd_url=VALID_CIMD_URL, created_by=self.user
        )
        metadata = _make_metadata(
            posthog_verification_token="phvt_fake_top_level",
            com_posthog={"verification_token": plaintext_nested},
        )
        mock_get.return_value = _mock_response(metadata, headers={})
        app = fetch_and_upsert_cimd_application(VALID_CIMD_URL)

        assert app is not None
        self.assertEqual(app.organization_id, self.organization.id)

    # (d) continued: a nested token that resolves but is bound to a different URL must not
    # fall through to a valid legacy token bound to this one — a recognized nested token
    # forecloses the legacy fallback regardless of whether the legacy token would itself verify.
    @patch("posthog.api.oauth.cimd.requests.Session.get")
    def test_nested_token_bound_elsewhere_does_not_fall_back_to_legacy(self, mock_get, _url_mock):
        other_url = "https://other.example.com/.well-known/oauth-client-metadata.json"
        other_org = Organization.objects.create(name="Other org")
        _, plaintext_nested = create_cimd_verification_token(
            organization=other_org, label="Nested partner elsewhere", cimd_url=other_url, created_by=self.user
        )
        _, plaintext_legacy = create_cimd_verification_token(
            organization=self.organization, label="Legacy partner here", cimd_url=VALID_CIMD_URL, created_by=self.user
        )
        metadata = _make_metadata(
            posthog_verification_token=plaintext_legacy,
            com_posthog={"verification_token": plaintext_nested},
        )
        mock_get.return_value = _mock_response(metadata, headers={})

        app = fetch_and_upsert_cimd_application(VALID_CIMD_URL)

        assert app is not None
        self.assertIsNone(app.organization_id)

    # (a) + (e) present scopes are written to application.scopes on creation.
    @parameterized.expand(
        [
            ("with_scopes", ["insight:read", "dashboard:write"], ["insight:read", "dashboard:write"]),
            ("empty", [], []),
        ]
    )
    @patch("posthog.api.oauth.cimd.requests.Session.get")
    def test_scopes_written_to_app_on_creation(self, _name, input_scopes, expected_scopes, mock_get, _url_mock):
        metadata = _make_metadata(com_posthog={"scopes": input_scopes})
        mock_get.return_value = _mock_response(metadata, headers={})

        app = fetch_and_upsert_cimd_application(VALID_CIMD_URL)

        assert app is not None
        self.assertEqual(sorted(app.scopes), sorted(expected_scopes))

    # (c) Only UNPRIVILEGED_SCOPES pass — privileged, hidden, and unknown strings are all dropped.
    @patch("posthog.api.oauth.cimd.requests.Session.get")
    def test_non_grantable_scopes_stripped(self, mock_get, _url_mock):
        hidden_scope = next(iter(OAUTH_SCOPES_HIDDEN)) if OAUTH_SCOPES_HIDDEN else None
        input_scopes = [
            *sorted(PRIVILEGED_SCOPES),
            "not_a_real_scope:write",  # unknown / garbage string
            "insight:read",  # legitimate — must survive
        ]
        if hidden_scope:
            input_scopes.append(hidden_scope)

        metadata = _make_metadata(com_posthog={"scopes": input_scopes})
        mock_get.return_value = _mock_response(metadata, headers={})

        app = fetch_and_upsert_cimd_application(VALID_CIMD_URL)

        assert app is not None
        for privileged_scope in PRIVILEGED_SCOPES:
            self.assertNotIn(privileged_scope, app.scopes)
        self.assertNotIn("not_a_real_scope:write", app.scopes)
        if hidden_scope:
            self.assertNotIn(hidden_scope, app.scopes)
        self.assertIn("insight:read", app.scopes)

    # Duplicate scopes in the metadata array collapse to one entry, order preserved.
    @patch("posthog.api.oauth.cimd.requests.Session.get")
    def test_duplicate_scopes_deduped(self, mock_get, _url_mock):
        metadata = _make_metadata(com_posthog={"scopes": ["insight:read", "dashboard:write", "insight:read"]})
        mock_get.return_value = _mock_response(metadata, headers={})

        app = fetch_and_upsert_cimd_application(VALID_CIMD_URL)

        assert app is not None
        self.assertEqual(app.scopes, ["insight:read", "dashboard:write"])

    # (b) absent com.posthog.scopes on refresh leaves existing scopes untouched.
    @patch("posthog.api.oauth.cimd.requests.Session.get")
    def test_absent_scopes_on_refresh_leaves_existing_untouched(self, mock_get, _url_mock):
        metadata_create = _make_metadata(com_posthog={"scopes": ["insight:read"]})
        mock_get.return_value = _mock_response(metadata_create, headers={})
        fetch_and_upsert_cimd_application(VALID_CIMD_URL)

        real_cache.delete(_fetch_lock_key(VALID_CIMD_URL))
        # Refresh with metadata that has no com.posthog.scopes.
        mock_get.return_value = _mock_response(_make_metadata(), headers={})
        refreshed = fetch_and_upsert_cimd_application(VALID_CIMD_URL)

        assert refreshed is not None
        self.assertIn("insight:read", refreshed.scopes)

    # (a) present scopes on refresh override the existing application.scopes.
    @patch("posthog.api.oauth.cimd.requests.Session.get")
    def test_present_scopes_on_refresh_override_existing(self, mock_get, _url_mock):
        metadata_create = _make_metadata(com_posthog={"scopes": ["insight:read", "dashboard:write"]})
        mock_get.return_value = _mock_response(metadata_create, headers={})
        fetch_and_upsert_cimd_application(VALID_CIMD_URL)

        real_cache.delete(_fetch_lock_key(VALID_CIMD_URL))
        metadata_refresh = _make_metadata(com_posthog={"scopes": ["survey:read"]})
        mock_get.return_value = _mock_response(metadata_refresh, headers={})
        refreshed = fetch_and_upsert_cimd_application(VALID_CIMD_URL)

        assert refreshed is not None
        self.assertEqual(refreshed.scopes, ["survey:read"])

    # com.posthog.optional_scopes carries the required/optional split: required `scopes` and the
    # declinable `optional_scopes` are written together on creation, capped to grantable scopes.
    @patch("posthog.api.oauth.cimd.requests.Session.get")
    def test_optional_scopes_written_to_app_on_creation(self, mock_get, _url_mock):
        metadata = _make_metadata(
            com_posthog={"scopes": ["insight:read"], "optional_scopes": ["dashboard:read", "llm_gateway:read"]}
        )
        mock_get.return_value = _mock_response(metadata, headers={})

        app = fetch_and_upsert_cimd_application(VALID_CIMD_URL)

        assert app is not None
        self.assertEqual(app.scopes, ["insight:read"])
        # llm_gateway:read is privileged, stripped by the grantable filter.
        self.assertEqual(app.optional_scopes, ["dashboard:read"])
        self.assertEqual(app.required_scopes, ["insight:read"])

    # Both fields refresh together so the split never drifts: a metadata refresh rewrites
    # `optional_scopes` alongside `scopes`.
    @patch("posthog.api.oauth.cimd.requests.Session.get")
    def test_optional_scopes_refresh_together_with_scopes(self, mock_get, _url_mock):
        mock_get.return_value = _mock_response(
            _make_metadata(com_posthog={"scopes": ["insight:read"], "optional_scopes": ["dashboard:read"]}), headers={}
        )
        fetch_and_upsert_cimd_application(VALID_CIMD_URL)

        real_cache.delete(_fetch_lock_key(VALID_CIMD_URL))
        mock_get.return_value = _mock_response(
            _make_metadata(com_posthog={"scopes": ["survey:read"], "optional_scopes": ["experiment:read"]}), headers={}
        )
        refreshed = fetch_and_upsert_cimd_application(VALID_CIMD_URL)

        assert refreshed is not None
        self.assertEqual(refreshed.scopes, ["survey:read"])
        self.assertEqual(refreshed.optional_scopes, ["experiment:read"])

    # Guard for the "scope ceiling bypass" review finding: a CIMD client controls its own
    # metadata document, but republishing it on refresh can never escalate the ceiling past
    # the unprivileged allow-list — privileged, hidden, and unknown scopes are stripped on
    # the refresh path exactly as on creation.
    @patch("posthog.api.oauth.cimd.requests.Session.get")
    def test_refresh_cannot_grant_non_grantable_scopes(self, mock_get, _url_mock):
        mock_get.return_value = _mock_response(_make_metadata(com_posthog={"scopes": ["insight:read"]}), headers={})
        fetch_and_upsert_cimd_application(VALID_CIMD_URL)

        real_cache.delete(_fetch_lock_key(VALID_CIMD_URL))
        hidden_scope = next(iter(OAUTH_SCOPES_HIDDEN)) if OAUTH_SCOPES_HIDDEN else None
        escalated = [*sorted(PRIVILEGED_SCOPES), "not_a_real_scope:write", "insight:read"]
        if hidden_scope:
            escalated.append(hidden_scope)
        mock_get.return_value = _mock_response(_make_metadata(com_posthog={"scopes": escalated}), headers={})
        refreshed = fetch_and_upsert_cimd_application(VALID_CIMD_URL)

        assert refreshed is not None
        for privileged_scope in PRIVILEGED_SCOPES:
            self.assertNotIn(privileged_scope, refreshed.scopes)
        self.assertNotIn("not_a_real_scope:write", refreshed.scopes)
        if hidden_scope:
            self.assertNotIn(hidden_scope, refreshed.scopes)
        self.assertEqual(refreshed.scopes, ["insight:read"])

    # absent com.posthog.scopes on initial creation → empty scopes list.
    @patch("posthog.api.oauth.cimd.requests.Session.get")
    def test_absent_scopes_on_creation_yields_empty_list(self, mock_get, _url_mock):
        mock_get.return_value = _mock_response(_make_metadata(), headers={})
        app = fetch_and_upsert_cimd_application(VALID_CIMD_URL)

        assert app is not None
        self.assertEqual(app.scopes, [])

    # A present, non-empty com.posthog.scopes that strips to nothing is rejected, not
    # stored as [] (which would widen the app to the broad UNPRIVILEGED default via the
    # empty-ceiling fallback). Mirrors DCR's all-stripped rejection; no app is created.
    @patch("posthog.api.oauth.cimd.requests.Session.get")
    def test_all_non_grantable_scopes_on_creation_rejected(self, mock_get, _url_mock):
        only_non_grantable = [*sorted(PRIVILEGED_SCOPES), "not_a_real_scope:write"]
        mock_get.return_value = _mock_response(_make_metadata(com_posthog={"scopes": only_non_grantable}), headers={})

        with self.assertRaises(CIMDValidationError):
            fetch_and_upsert_cimd_application(VALID_CIMD_URL)

        self.assertFalse(OAuthApplication.objects.filter(client_id=VALID_CIMD_URL).exists())

    # On refresh, a doc whose scopes all strip out is rejected and the existing ceiling is
    # left untouched (fail-closed) rather than widened to the default.
    @patch("posthog.api.oauth.cimd.requests.Session.get")
    def test_all_non_grantable_scopes_on_refresh_leaves_existing_untouched(self, mock_get, _url_mock):
        mock_get.return_value = _mock_response(_make_metadata(com_posthog={"scopes": ["insight:read"]}), headers={})
        created = fetch_and_upsert_cimd_application(VALID_CIMD_URL)
        assert created is not None

        real_cache.delete(_fetch_lock_key(VALID_CIMD_URL))
        only_non_grantable = [*sorted(PRIVILEGED_SCOPES), "not_a_real_scope:write"]
        mock_get.return_value = _mock_response(_make_metadata(com_posthog={"scopes": only_non_grantable}), headers={})

        with self.assertRaises(CIMDValidationError):
            fetch_and_upsert_cimd_application(VALID_CIMD_URL)

        created.refresh_from_db()
        self.assertEqual(created.scopes, ["insight:read"])


class TestResolveScopes(SimpleTestCase):
    """`_resolve_scopes` parsing in isolation — no DB, so it runs without local services."""

    def test_absent_or_malformed_field_returns_none(self) -> None:
        self.assertIsNone(_resolve_scopes({}))
        self.assertIsNone(_resolve_scopes({"com.posthog": {}}))
        # Malformed partner JSON: a non-list scopes value hits the runtime guard and returns None.
        self.assertIsNone(_resolve_scopes(cast(CIMDMetadataDocument, {"com.posthog": {"scopes": "not-a-list"}})))

    def test_explicit_empty_list_is_use_default(self) -> None:
        # Distinct from all-stripped: an explicitly empty array is the legitimate "use default" signal.
        self.assertEqual(_resolve_scopes({"com.posthog": {"scopes": []}}), [])

    def test_partial_strip_keeps_grantable(self) -> None:
        resolved = _resolve_scopes({"com.posthog": {"scopes": ["insight:read", "llm_gateway:read"]}})
        self.assertEqual(resolved, ["insight:read"])

    def test_all_non_grantable_raises(self) -> None:
        with self.assertRaises(CIMDValidationError):
            _resolve_scopes({"com.posthog": {"scopes": ["llm_gateway:read", "not_a_real_scope:write"]}})
