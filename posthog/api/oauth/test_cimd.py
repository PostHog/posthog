import json
import base64
import hashlib
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
    CIMD_PROVISIONING_ACCOUNT_REQUESTS_DEFAULT_RATE_LIMIT,
    CIMD_PROVISIONING_ACCOUNT_REQUESTS_VERIFIED_RATE_LIMIT,
    CIMDFetchError,
    CIMDMetadataDocument,
    CIMDValidationError,
    _fetch_lock_key,
    _resolve_scopes,
    fetch_and_upsert_cimd_application,
    fetch_cimd_metadata,
    get_application_by_client_id,
    get_or_create_cimd_application,
    get_or_create_cimd_provisioning_application,
    is_cimd_client_id,
    refresh_cimd_metadata_task,
    register_cimd_provisioning_application_task,
    validate_cimd_url,
)
from posthog.api.oauth.client_name import sanitize_client_name
from posthog.models.oauth import OAuthApplication, create_cimd_verification_token
from posthog.scopes import OAUTH_HIDDEN_SCOPES, PRIVILEGED_SCOPES

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


@patch("posthog.api.oauth.cimd.is_url_allowed", return_value=(True, None))
class TestFetchCimdMetadata(APIBaseTest):
    @patch("posthog.api.oauth.cimd.requests.get")
    def test_success(self, mock_get, _url_mock):
        metadata = _make_metadata()
        mock_get.return_value = _mock_response(metadata, headers={"Cache-Control": "max-age=3600"})
        result, ttl = fetch_cimd_metadata(VALID_CIMD_URL)

        assert "client_name" in result
        self.assertEqual(result["client_name"], "Test MCP Client")
        self.assertEqual(ttl, 3600)

    @patch("posthog.api.oauth.cimd.requests.get")
    def test_client_id_mismatch(self, mock_get, _url_mock):
        metadata = _make_metadata(client_id="https://wrong.example.com/other.json")
        mock_get.return_value = _mock_response(metadata)
        with self.assertRaises(CIMDValidationError) as ctx:
            fetch_cimd_metadata(VALID_CIMD_URL)
        self.assertIn("does not match", str(ctx.exception))

    @patch("posthog.api.oauth.cimd.requests.get")
    def test_too_large(self, mock_get, _url_mock):
        resp = _mock_response(_make_metadata())
        resp.iter_content = MagicMock(return_value=iter([b"x" * 6000]))
        resp.headers = {"Content-Length": "6000"}
        mock_get.return_value = resp
        with self.assertRaises(CIMDValidationError) as ctx:
            fetch_cimd_metadata(VALID_CIMD_URL)
        self.assertIn("limit", str(ctx.exception))

    @patch("posthog.api.oauth.cimd.requests.get")
    def test_invalid_json(self, mock_get, _url_mock):
        resp = _mock_response()
        resp.status_code = 200
        resp.iter_content = MagicMock(return_value=iter([b"not json"]))
        resp.headers = {}
        mock_get.return_value = resp
        with self.assertRaises(CIMDValidationError):
            fetch_cimd_metadata(VALID_CIMD_URL)

    @patch("posthog.api.oauth.cimd.requests.get")
    def test_missing_redirect_uris(self, mock_get, _url_mock):
        metadata = _make_metadata()
        del metadata["redirect_uris"]
        mock_get.return_value = _mock_response(metadata)
        with self.assertRaises(CIMDValidationError) as ctx:
            fetch_cimd_metadata(VALID_CIMD_URL)
        self.assertIn("redirect_uris", str(ctx.exception))

    @patch("posthog.api.oauth.cimd.requests.get")
    def test_redirect_uri_with_whitespace_rejected(self, mock_get, _url_mock):
        metadata = _make_metadata(redirect_uris=["https://legit.com/callback https://attacker.com/steal"])
        mock_get.return_value = _mock_response(metadata)
        with self.assertRaises(CIMDValidationError) as ctx:
            fetch_cimd_metadata(VALID_CIMD_URL)
        self.assertEqual(str(ctx.exception), "redirect_uri must not contain whitespace")

    @patch("posthog.api.oauth.cimd.requests.get")
    def test_non_200_response(self, mock_get, _url_mock):
        mock_get.return_value = _mock_response(status_code=404)
        with self.assertRaises(CIMDFetchError) as ctx:
            fetch_cimd_metadata(VALID_CIMD_URL)
        self.assertIn("404", str(ctx.exception))

    @patch("posthog.api.oauth.cimd.requests.get")
    def test_timeout(self, mock_get, _url_mock):
        mock_get.side_effect = requests.Timeout("Connection timed out")
        with self.assertRaises(CIMDFetchError):
            fetch_cimd_metadata(VALID_CIMD_URL)

    @patch("posthog.api.oauth.cimd.requests.get")
    def test_forbidden_auth_method(self, mock_get, _url_mock):
        metadata = _make_metadata(token_endpoint_auth_method="client_secret_post")
        mock_get.return_value = _mock_response(metadata)
        with self.assertRaises(CIMDValidationError) as ctx:
            fetch_cimd_metadata(VALID_CIMD_URL)
        self.assertIn("client_secret_post", str(ctx.exception))

    @patch("posthog.api.oauth.cimd.requests.get")
    def test_cache_ttl_clamped_to_minimum(self, mock_get, _url_mock):
        metadata = _make_metadata()
        mock_get.return_value = _mock_response(metadata, headers={"Cache-Control": "max-age=10"})
        _, ttl = fetch_cimd_metadata(VALID_CIMD_URL)
        self.assertEqual(ttl, 300)  # Clamped to 5 min minimum

    @patch("posthog.api.oauth.cimd.requests.get")
    def test_cache_ttl_clamped_to_maximum(self, mock_get, _url_mock):
        metadata = _make_metadata()
        mock_get.return_value = _mock_response(metadata, headers={"Cache-Control": "max-age=999999"})
        _, ttl = fetch_cimd_metadata(VALID_CIMD_URL)
        self.assertEqual(ttl, 86400)  # Clamped to 24h maximum

    @patch("posthog.api.oauth.cimd.requests.get")
    def test_default_cache_ttl(self, mock_get, _url_mock):
        metadata = _make_metadata()
        mock_get.return_value = _mock_response(metadata, headers={})
        _, ttl = fetch_cimd_metadata(VALID_CIMD_URL)
        self.assertEqual(ttl, 3600)  # Default 1 hour


@patch("posthog.api.oauth.cimd.is_url_allowed", return_value=(True, None))
class TestFetchAndUpsertCimdApplication(APIBaseTest):
    """Tests for fetch_and_upsert_cimd_application — the core fetch+create/update function."""

    @patch("posthog.api.oauth.cimd.requests.get")
    def test_creates_new_application(self, mock_get, _url_mock):
        metadata = _make_metadata(logo_uri="https://example.com/logo.png")
        mock_get.return_value = _mock_response(metadata, headers={})

        app = fetch_and_upsert_cimd_application(VALID_CIMD_URL)

        self.assertIsNotNone(app)
        assert app is not None
        self.assertTrue(app.is_cimd_client)
        self.assertFalse(app.is_dcr_client)
        self.assertEqual(app.cimd_metadata_url, VALID_CIMD_URL)
        self.assertEqual(app.name, "Test MCP Client")
        self.assertEqual(app.redirect_uris, "http://127.0.0.1:3000/callback")
        self.assertEqual(app.logo_uri, "https://example.com/logo.png")
        self.assertIsNotNone(app.cimd_metadata_last_fetched)
        self.assertIsNone(app.organization)
        self.assertIsNone(app.user)

    @patch("posthog.api.oauth.cimd.requests.get")
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

    @patch("posthog.api.oauth.cimd.requests.get")
    def test_returns_none_when_lock_held(self, mock_get, _url_mock):
        # Simulate another caller holding the lock
        real_cache.set(_fetch_lock_key(VALID_CIMD_URL), True, timeout=30)

        result = fetch_and_upsert_cimd_application(VALID_CIMD_URL)
        self.assertIsNone(result)
        mock_get.assert_not_called()

        real_cache.delete(_fetch_lock_key(VALID_CIMD_URL))

    @patch("posthog.api.oauth.cimd.requests.get")
    def test_blocked_name_uses_default(self, mock_get, _url_mock):
        metadata = _make_metadata(client_name="PostHog Official Client")
        mock_get.return_value = _mock_response(metadata, headers={})

        app = fetch_and_upsert_cimd_application(VALID_CIMD_URL)
        assert app is not None
        self.assertEqual(app.name, "CIMD Client")

    @patch("posthog.api.oauth.cimd.requests.get")
    def test_fetch_failure_propagates(self, mock_get, _url_mock):
        mock_get.side_effect = requests.ConnectionError("DNS resolution failed")
        with self.assertRaises(CIMDFetchError):
            fetch_and_upsert_cimd_application(VALID_CIMD_URL)

    @patch("posthog.api.oauth.cimd.requests.get")
    def test_releases_lock_on_failure(self, mock_get, _url_mock):
        mock_get.side_effect = requests.ConnectionError("DNS failed")
        with self.assertRaises(CIMDFetchError):
            fetch_and_upsert_cimd_application(VALID_CIMD_URL)

        # Lock should be released — a subsequent call should acquire it
        self.assertIsNone(real_cache.get(_fetch_lock_key(VALID_CIMD_URL)))


@patch("posthog.api.oauth.cimd.is_url_allowed", return_value=(True, None))
class TestGetOrCreateCimdApplication(APIBaseTest):
    """Tests for get_or_create_cimd_application — the orchestration layer."""

    @patch("posthog.api.oauth.cimd.requests.get")
    def test_returns_existing_when_cache_fresh(self, mock_get, _url_mock):
        metadata = _make_metadata()
        mock_get.return_value = _mock_response(metadata, headers={})

        app1 = get_or_create_cimd_application(VALID_CIMD_URL)
        app2 = get_or_create_cimd_application(VALID_CIMD_URL)

        self.assertEqual(app1.pk, app2.pk)
        self.assertEqual(mock_get.call_count, 1)

    @patch("posthog.api.oauth.cimd.cache")
    @patch("posthog.api.oauth.cimd.requests.get")
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

    @patch("posthog.api.oauth.cimd.requests.get")
    def test_new_client_fetch_failure_raises(self, mock_get, _url_mock):
        mock_get.side_effect = requests.ConnectionError("DNS resolution failed")
        with self.assertRaises(CIMDFetchError):
            get_or_create_cimd_application(VALID_CIMD_URL)

    @patch("posthog.api.oauth.cimd.requests.get")
    def test_refresh_task_updates_metadata(self, mock_get, _url_mock):
        metadata1 = _make_metadata(client_name="Original Name")
        mock_get.return_value = _mock_response(metadata1, headers={})
        fetch_and_upsert_cimd_application(VALID_CIMD_URL)

        metadata2 = _make_metadata(client_name="Updated Name", logo_uri="https://example.com/new-logo.png")
        mock_get.return_value = _mock_response(metadata2, headers={})
        refresh_cimd_metadata_task(VALID_CIMD_URL)

        app = OAuthApplication.objects.get(cimd_metadata_url=VALID_CIMD_URL)
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
    @patch("posthog.api.oauth.cimd.requests.get")
    def test_client_name_from_metadata_is_html_escaped(self, _name, payload, mock_get, _url_mock):
        mock_get.return_value = _mock_response(_make_metadata(client_name=payload), headers={})

        app = fetch_and_upsert_cimd_application(VALID_CIMD_URL)

        assert app is not None
        expected = sanitize_client_name(payload)
        self.assertEqual(app.name, expected)
        self.assertNotIn("<", app.name)
        self.assertNotIn(">", app.name)

    @patch("posthog.api.oauth.cimd.requests.get")
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

        app = OAuthApplication.objects.get(cimd_metadata_url=VALID_CIMD_URL)
        self.assertEqual(app.name, escape(payload))
        self.assertNotIn("<", app.name)

    @patch("posthog.api.oauth.cimd.requests.get")
    def test_refresh_task_handles_fetch_failure_gracefully(self, mock_get, _url_mock):
        metadata = _make_metadata(client_name="Original Name")
        mock_get.return_value = _mock_response(metadata, headers={})
        fetch_and_upsert_cimd_application(VALID_CIMD_URL)

        mock_get.side_effect = requests.ConnectionError("DNS failed")
        refresh_cimd_metadata_task(VALID_CIMD_URL)

        app = OAuthApplication.objects.get(cimd_metadata_url=VALID_CIMD_URL)
        self.assertEqual(app.name, "Original Name")

    @parameterized.expand(
        [
            ("refresh", refresh_cimd_metadata_task),
            ("registration", register_cimd_provisioning_application_task),
        ]
    )
    @patch("posthog.api.oauth.cimd.capture_exception")
    @patch("posthog.api.oauth.cimd.fetch_and_upsert_cimd_application")
    def test_background_task_does_not_capture_expected_validation_error(
        self, _name, task_fn, mock_fetch, mock_capture, _url_mock
    ):
        # Rejecting a non-compliant partner document is expected, so it must not surface as an error-tracking issue.
        mock_fetch.side_effect = CIMDValidationError("document exceeds the 5120 byte limit")
        task_fn(VALID_CIMD_URL)
        mock_capture.assert_not_called()

    @parameterized.expand(
        [
            ("refresh", refresh_cimd_metadata_task),
            ("registration", register_cimd_provisioning_application_task),
        ]
    )
    @patch("posthog.api.oauth.cimd.capture_exception")
    @patch("posthog.api.oauth.cimd.fetch_and_upsert_cimd_application")
    def test_background_task_captures_unexpected_fetch_error(self, _name, task_fn, mock_fetch, mock_capture, _url_mock):
        error = CIMDFetchError("connection reset")
        mock_fetch.side_effect = error
        task_fn(VALID_CIMD_URL)
        mock_capture.assert_called_once_with(error)


class TestGetApplicationByClientId(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.standard_app = OAuthApplication.objects.create(
            name="Standard App",
            client_id="standard-uuid-id",
            client_secret="secret",
            client_type=OAuthApplication.CLIENT_PUBLIC,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://example.com/callback",
            algorithm="RS256",
        )
        self.cimd_app = OAuthApplication.objects.create(
            name="CIMD App",
            client_secret="secret",
            client_type=OAuthApplication.CLIENT_PUBLIC,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="http://127.0.0.1:3000/callback",
            algorithm="RS256",
            is_cimd_client=True,
            cimd_metadata_url=VALID_CIMD_URL,
        )

    def test_standard_uuid_lookup(self):
        result = get_application_by_client_id("standard-uuid-id")
        self.assertEqual(result.pk, self.standard_app.pk)

    def test_cimd_url_lookup(self):
        result = get_application_by_client_id(VALID_CIMD_URL)
        self.assertEqual(result.pk, self.cimd_app.pk)

    def test_standard_uuid_not_found(self):
        with self.assertRaises(OAuthApplication.DoesNotExist):
            get_application_by_client_id("nonexistent-uuid")

    def test_cimd_url_not_found(self):
        with self.assertRaises(OAuthApplication.DoesNotExist):
            get_application_by_client_id("https://unknown.example.com/.well-known/oauth-client-metadata.json")


@patch("posthog.api.oauth.cimd.is_url_allowed", return_value=(True, None))
class TestGetOrCreateCimdProvisioningApplication(APIBaseTest):
    @patch("posthog.api.oauth.cimd.requests.get")
    def test_creates_new_app_with_provisioning_defaults(self, mock_get, _url_mock):
        mock_get.return_value = _mock_response(_make_metadata(), headers={})

        app = get_or_create_cimd_provisioning_application(VALID_CIMD_URL)
        assert app is not None

        self.assertTrue(app.is_cimd_client)
        self.assertEqual(app.cimd_metadata_url, VALID_CIMD_URL)
        self.assertEqual(app.provisioning_auth_method, "pkce")
        self.assertTrue(app.provisioning_active)
        self.assertTrue(app.provisioning_can_create_accounts)
        self.assertTrue(app.provisioning_can_provision_resources)
        self.assertEqual(
            app.provisioning_rate_limit_account_requests,
            CIMD_PROVISIONING_ACCOUNT_REQUESTS_DEFAULT_RATE_LIMIT,
        )

    @patch("posthog.api.oauth.cimd.posthoganalytics.capture")
    @patch("posthog.api.oauth.cimd.requests.get")
    def test_emits_registration_event_on_provisioning_upgrade(self, mock_get, mock_capture, _url_mock):
        mock_get.return_value = _mock_response(_make_metadata(), headers={})

        get_or_create_cimd_provisioning_application(VALID_CIMD_URL)

        events = [call.kwargs.get("event") for call in mock_capture.call_args_list]
        self.assertIn("cimd_provisioning_partner_registered", events)

    @patch("posthog.api.oauth.cimd.posthoganalytics.capture")
    @patch("posthog.api.oauth.cimd.requests.get")
    def test_no_event_when_provisioning_already_configured(self, mock_get, mock_capture, _url_mock):
        mock_get.return_value = _mock_response(_make_metadata(), headers={})
        get_or_create_cimd_provisioning_application(VALID_CIMD_URL)
        mock_capture.reset_mock()

        get_or_create_cimd_provisioning_application(VALID_CIMD_URL)

        events = [call.kwargs.get("event") for call in mock_capture.call_args_list]
        self.assertNotIn("cimd_provisioning_partner_registered", events)

    @patch("posthog.api.oauth.cimd.requests.get")
    def test_backfills_provisioning_defaults_on_existing_cimd_app(self, mock_get, _url_mock):
        mock_get.return_value = _mock_response(_make_metadata(), headers={})
        existing = fetch_and_upsert_cimd_application(VALID_CIMD_URL)
        assert existing is not None
        self.assertFalse(existing.is_provisioning_partner)

        app = get_or_create_cimd_provisioning_application(VALID_CIMD_URL)
        assert app is not None

        self.assertEqual(app.pk, existing.pk)
        self.assertEqual(app.provisioning_auth_method, "pkce")
        self.assertTrue(app.provisioning_active)
        self.assertTrue(app.provisioning_can_create_accounts)
        self.assertTrue(app.provisioning_can_provision_resources)

    @patch("posthog.api.oauth.cimd.requests.get")
    def test_preserves_existing_provisioning_config(self, mock_get, _url_mock):
        mock_get.return_value = _mock_response(_make_metadata(), headers={})
        existing = fetch_and_upsert_cimd_application(VALID_CIMD_URL)
        assert existing is not None
        existing.provisioning_auth_method = "hmac"
        existing.provisioning_active = False
        existing.provisioning_can_create_accounts = False
        existing.save(
            update_fields=["provisioning_auth_method", "provisioning_active", "provisioning_can_create_accounts"]
        )

        app = get_or_create_cimd_provisioning_application(VALID_CIMD_URL)
        assert app is not None

        self.assertEqual(app.provisioning_auth_method, "hmac")
        self.assertFalse(app.provisioning_active)
        self.assertFalse(app.provisioning_can_create_accounts)

    @patch("posthog.api.oauth.cimd.requests.get")
    def test_fetch_failure_raises(self, mock_get, _url_mock):
        mock_get.side_effect = requests.ConnectionError("DNS resolution failed")
        with self.assertRaises(CIMDFetchError):
            get_or_create_cimd_provisioning_application(VALID_CIMD_URL)

    def test_blocked_url_returns_none(self, _url_mock):
        from posthog.api.oauth.cimd import block_cimd_url, unblock_cimd_url

        block_cimd_url(VALID_CIMD_URL)
        result = get_or_create_cimd_provisioning_application(VALID_CIMD_URL)
        self.assertIsNone(result)

        unblock_cimd_url(VALID_CIMD_URL)

    @patch("posthog.api.oauth.cimd.requests.get")
    def test_blocked_url_prevents_fetch(self, mock_get, _url_mock):
        from posthog.api.oauth.cimd import block_cimd_url, unblock_cimd_url

        block_cimd_url(VALID_CIMD_URL)
        result = fetch_and_upsert_cimd_application(VALID_CIMD_URL)
        self.assertIsNone(result)
        mock_get.assert_not_called()

        unblock_cimd_url(VALID_CIMD_URL)


@patch("posthog.api.oauth.cimd.is_url_allowed", return_value=(True, None))
class TestCIMDVerificationToken(APIBaseTest):
    @patch("posthog.api.oauth.cimd.requests.get")
    def test_valid_verification_token_links_app_to_organization(self, mock_get, _url_mock):
        token, plaintext = create_cimd_verification_token(
            organization=self.organization, label="Test partner", created_by=self.user
        )
        metadata = _make_metadata(posthog_verification_token=plaintext)
        mock_get.return_value = _mock_response(metadata, headers={})

        app = fetch_and_upsert_cimd_application(VALID_CIMD_URL)

        assert app is not None
        self.assertEqual(app.organization_id, self.organization.id)
        token.refresh_from_db()
        self.assertIsNotNone(token.last_used_at)

    @patch("posthog.api.oauth.cimd.requests.get")
    def test_invalid_verification_token_leaves_app_unlinked(self, mock_get, _url_mock):
        metadata = _make_metadata(posthog_verification_token="phvt_totally_made_up")
        mock_get.return_value = _mock_response(metadata, headers={})

        app = fetch_and_upsert_cimd_application(VALID_CIMD_URL)

        assert app is not None
        self.assertIsNone(app.organization_id)

    @patch("posthog.api.oauth.cimd.requests.get")
    def test_missing_verification_token_leaves_app_unlinked(self, mock_get, _url_mock):
        mock_get.return_value = _mock_response(_make_metadata(), headers={})

        app = fetch_and_upsert_cimd_application(VALID_CIMD_URL)

        assert app is not None
        self.assertIsNone(app.organization_id)

    @patch("posthog.api.oauth.cimd.requests.get")
    def test_verified_partner_gets_higher_rate_limit(self, mock_get, _url_mock):
        _, plaintext = create_cimd_verification_token(
            organization=self.organization, label="Verified partner", created_by=self.user
        )
        metadata = _make_metadata(posthog_verification_token=plaintext)
        mock_get.return_value = _mock_response(metadata, headers={})

        app = get_or_create_cimd_provisioning_application(VALID_CIMD_URL)

        assert app is not None
        self.assertEqual(app.organization_id, self.organization.id)
        self.assertEqual(
            app.provisioning_rate_limit_account_requests,
            CIMD_PROVISIONING_ACCOUNT_REQUESTS_VERIFIED_RATE_LIMIT,
        )

    @patch("posthog.api.oauth.cimd.requests.get")
    def test_unverified_partner_gets_default_rate_limit(self, mock_get, _url_mock):
        mock_get.return_value = _mock_response(_make_metadata(), headers={})

        app = get_or_create_cimd_provisioning_application(VALID_CIMD_URL)

        assert app is not None
        self.assertIsNone(app.organization_id)
        self.assertEqual(
            app.provisioning_rate_limit_account_requests,
            CIMD_PROVISIONING_ACCOUNT_REQUESTS_DEFAULT_RATE_LIMIT,
        )

    @patch("posthog.api.oauth.cimd.requests.get")
    def test_refresh_unlinks_app_when_token_removed(self, mock_get, _url_mock):
        _, plaintext = create_cimd_verification_token(
            organization=self.organization, label="Rotating partner", created_by=self.user
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

    @patch("posthog.api.oauth.cimd.requests.get")
    def test_refresh_links_app_when_token_added(self, mock_get, _url_mock):
        # First fetch: no token → unlinked
        mock_get.return_value = _mock_response(_make_metadata(), headers={})
        app = fetch_and_upsert_cimd_application(VALID_CIMD_URL)
        assert app is not None
        self.assertIsNone(app.organization_id)

        # Partner adds a token and we refetch
        _, plaintext = create_cimd_verification_token(
            organization=self.organization, label="Added later", created_by=self.user
        )
        real_cache.delete(_fetch_lock_key(VALID_CIMD_URL))
        mock_get.return_value = _mock_response(_make_metadata(posthog_verification_token=plaintext), headers={})
        refreshed = fetch_and_upsert_cimd_application(VALID_CIMD_URL)
        assert refreshed is not None
        self.assertEqual(refreshed.organization_id, self.organization.id)

    @patch("posthog.api.oauth.cimd.requests.get")
    def test_non_string_verification_token_is_ignored(self, mock_get, _url_mock):
        metadata = _make_metadata()
        metadata["posthog_verification_token"] = {"not": "a string"}
        mock_get.return_value = _mock_response(metadata, headers={})

        app = fetch_and_upsert_cimd_application(VALID_CIMD_URL)

        assert app is not None
        self.assertIsNone(app.organization_id)

    @patch("posthog.api.oauth.cimd.requests.get")
    def test_refresh_bumps_rate_limit_when_token_added_post_registration(self, mock_get, _url_mock):
        mock_get.return_value = _mock_response(_make_metadata(), headers={})
        get_or_create_cimd_provisioning_application(VALID_CIMD_URL)
        app = OAuthApplication.objects.get(cimd_metadata_url=VALID_CIMD_URL)
        self.assertIsNone(app.organization_id)
        self.assertEqual(
            app.provisioning_rate_limit_account_requests,
            CIMD_PROVISIONING_ACCOUNT_REQUESTS_DEFAULT_RATE_LIMIT,
        )

        _, plaintext = create_cimd_verification_token(
            organization=self.organization, label="Added post-registration", created_by=self.user
        )
        real_cache.delete(_fetch_lock_key(VALID_CIMD_URL))
        mock_get.return_value = _mock_response(_make_metadata(posthog_verification_token=plaintext), headers={})
        refreshed = fetch_and_upsert_cimd_application(VALID_CIMD_URL)

        assert refreshed is not None
        self.assertEqual(refreshed.organization_id, self.organization.id)
        self.assertEqual(
            refreshed.provisioning_rate_limit_account_requests,
            CIMD_PROVISIONING_ACCOUNT_REQUESTS_VERIFIED_RATE_LIMIT,
        )

    @patch("posthog.api.oauth.cimd.requests.get")
    def test_refresh_drops_rate_limit_when_token_removed(self, mock_get, _url_mock):
        _, plaintext = create_cimd_verification_token(
            organization=self.organization, label="Rotating partner", created_by=self.user
        )
        mock_get.return_value = _mock_response(_make_metadata(posthog_verification_token=plaintext), headers={})
        get_or_create_cimd_provisioning_application(VALID_CIMD_URL)
        app = OAuthApplication.objects.get(cimd_metadata_url=VALID_CIMD_URL)
        self.assertEqual(app.organization_id, self.organization.id)
        self.assertEqual(
            app.provisioning_rate_limit_account_requests,
            CIMD_PROVISIONING_ACCOUNT_REQUESTS_VERIFIED_RATE_LIMIT,
        )

        real_cache.delete(_fetch_lock_key(VALID_CIMD_URL))
        mock_get.return_value = _mock_response(_make_metadata(), headers={})
        refreshed = fetch_and_upsert_cimd_application(VALID_CIMD_URL)

        assert refreshed is not None
        self.assertIsNone(refreshed.organization_id)
        self.assertEqual(
            refreshed.provisioning_rate_limit_account_requests,
            CIMD_PROVISIONING_ACCOUNT_REQUESTS_DEFAULT_RATE_LIMIT,
        )

    @patch("posthog.api.oauth.cimd.requests.get")
    def test_refresh_preserves_admin_custom_rate_limit(self, mock_get, _url_mock):
        mock_get.return_value = _mock_response(_make_metadata(), headers={})
        get_or_create_cimd_provisioning_application(VALID_CIMD_URL)
        app = OAuthApplication.objects.get(cimd_metadata_url=VALID_CIMD_URL)
        app.provisioning_rate_limit_account_requests = 250
        app.provisioning_rate_limit_account_requests_source = "admin"
        app.save(
            update_fields=[
                "provisioning_rate_limit_account_requests",
                "provisioning_rate_limit_account_requests_source",
            ]
        )

        _, plaintext = create_cimd_verification_token(
            organization=self.organization, label="Post-admin-override", created_by=self.user
        )
        real_cache.delete(_fetch_lock_key(VALID_CIMD_URL))
        mock_get.return_value = _mock_response(_make_metadata(posthog_verification_token=plaintext), headers={})
        refreshed = fetch_and_upsert_cimd_application(VALID_CIMD_URL)

        assert refreshed is not None
        self.assertEqual(refreshed.organization_id, self.organization.id)
        self.assertEqual(refreshed.provisioning_rate_limit_account_requests, 250)
        self.assertEqual(refreshed.provisioning_rate_limit_account_requests_source, "admin")


class TestAuthorizationServerMetadata(APIBaseTest):
    def test_advertises_cimd_support(self):
        client = APIClient()
        response = client.get("/.well-known/oauth-authorization-server")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data.get("client_id_metadata_document_supported"))


@patch("posthog.api.oauth.cimd.is_url_allowed", return_value=(True, None))
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

    @patch("posthog.api.oauth.cimd.requests.get")
    def test_cimd_url_creates_app_and_returns_consent_screen(self, mock_get, _url_mock):
        metadata = _make_metadata()
        mock_get.return_value = _mock_response(metadata)
        url = self._authorize_url(VALID_CIMD_URL)

        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        app = OAuthApplication.objects.get(cimd_metadata_url=VALID_CIMD_URL)
        self.assertTrue(app.is_cimd_client)
        self.assertEqual(app.name, "Test MCP Client")
        mock_get.assert_called_once()

    @patch("posthog.api.oauth.cimd.requests.get")
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
        mock_get.assert_not_called()
        self.assertEqual(OAuthApplication.objects.filter(cimd_metadata_url=VALID_CIMD_URL).count(), 1)

    @patch("posthog.api.oauth.cimd.requests.get")
    def test_cimd_fetch_failure_rejects_new_client(self, mock_get, _url_mock):
        mock_get.side_effect = requests.ConnectionError("DNS failed")
        url = self._authorize_url(VALID_CIMD_URL)

        response = self.client.get(url)

        self.assertEqual(response.status_code, 400)
        self.assertIn("invalid", response.json().get("error", "").lower())

    @patch("posthog.api.oauth.cimd.requests.get")
    def test_cimd_mismatched_redirect_uri_rejected(self, mock_get, _url_mock):
        metadata = _make_metadata()
        mock_get.return_value = _mock_response(metadata)
        # Use a redirect_uri not in the CIMD metadata
        url = self._authorize_url(VALID_CIMD_URL, redirect_uri="https://evil.com/steal")

        response = self.client.get(url)

        self.assertEqual(response.status_code, 400)

    @patch("posthog.api.oauth.cimd.requests.get")
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
        mock_get.assert_not_called()

    def test_cimd_requires_authentication(self, _url_mock):
        self.client.logout()
        url = self._authorize_url(VALID_CIMD_URL)

        response = self.client.get(url)

        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response["Location"])


@patch("posthog.api.oauth.cimd.is_url_allowed", return_value=(True, None))
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
    @patch("posthog.api.oauth.cimd.requests.get")
    def test_verification_token_dual_read(self, token_placement, mock_get, _url_mock):
        token, plaintext = create_cimd_verification_token(
            organization=self.organization, label="Dual-read partner", created_by=self.user
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
    @patch("posthog.api.oauth.cimd.requests.get")
    def test_verification_token_falls_back_when_nested_unrecognized(self, mock_get, _url_mock):
        _, plaintext = create_cimd_verification_token(
            organization=self.organization, label="Fallback partner", created_by=self.user
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
    @patch("posthog.api.oauth.cimd.requests.get")
    def test_nested_token_takes_precedence_over_top_level(self, mock_get, _url_mock):
        _, plaintext_nested = create_cimd_verification_token(
            organization=self.organization, label="Nested partner", created_by=self.user
        )
        metadata = _make_metadata(
            posthog_verification_token="phvt_fake_top_level",
            com_posthog={"verification_token": plaintext_nested},
        )
        mock_get.return_value = _mock_response(metadata, headers={})
        app = fetch_and_upsert_cimd_application(VALID_CIMD_URL)

        assert app is not None
        self.assertEqual(app.organization_id, self.organization.id)

    # (a) + (e) present scopes are written to application.scopes on creation.
    @parameterized.expand(
        [
            ("with_scopes", ["insight:read", "dashboard:write"], ["insight:read", "dashboard:write"]),
            ("empty", [], []),
        ]
    )
    @patch("posthog.api.oauth.cimd.requests.get")
    def test_scopes_written_to_app_on_creation(self, _name, input_scopes, expected_scopes, mock_get, _url_mock):
        metadata = _make_metadata(com_posthog={"scopes": input_scopes})
        mock_get.return_value = _mock_response(metadata, headers={})

        app = fetch_and_upsert_cimd_application(VALID_CIMD_URL)

        assert app is not None
        self.assertEqual(sorted(app.scopes), sorted(expected_scopes))

    # (c) Only UNPRIVILEGED_SCOPES pass — privileged, hidden, and unknown strings are all dropped.
    @patch("posthog.api.oauth.cimd.requests.get")
    def test_non_grantable_scopes_stripped(self, mock_get, _url_mock):
        hidden_scope = next(iter(OAUTH_HIDDEN_SCOPES)) if OAUTH_HIDDEN_SCOPES else None
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
    @patch("posthog.api.oauth.cimd.requests.get")
    def test_duplicate_scopes_deduped(self, mock_get, _url_mock):
        metadata = _make_metadata(com_posthog={"scopes": ["insight:read", "dashboard:write", "insight:read"]})
        mock_get.return_value = _mock_response(metadata, headers={})

        app = fetch_and_upsert_cimd_application(VALID_CIMD_URL)

        assert app is not None
        self.assertEqual(app.scopes, ["insight:read", "dashboard:write"])

    # (b) absent com.posthog.scopes on refresh leaves existing scopes untouched.
    @patch("posthog.api.oauth.cimd.requests.get")
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
    @patch("posthog.api.oauth.cimd.requests.get")
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
    @patch("posthog.api.oauth.cimd.requests.get")
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
    @patch("posthog.api.oauth.cimd.requests.get")
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
    @patch("posthog.api.oauth.cimd.requests.get")
    def test_refresh_cannot_grant_non_grantable_scopes(self, mock_get, _url_mock):
        mock_get.return_value = _mock_response(_make_metadata(com_posthog={"scopes": ["insight:read"]}), headers={})
        fetch_and_upsert_cimd_application(VALID_CIMD_URL)

        real_cache.delete(_fetch_lock_key(VALID_CIMD_URL))
        hidden_scope = next(iter(OAUTH_HIDDEN_SCOPES)) if OAUTH_HIDDEN_SCOPES else None
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
    @patch("posthog.api.oauth.cimd.requests.get")
    def test_absent_scopes_on_creation_yields_empty_list(self, mock_get, _url_mock):
        mock_get.return_value = _mock_response(_make_metadata(), headers={})
        app = fetch_and_upsert_cimd_application(VALID_CIMD_URL)

        assert app is not None
        self.assertEqual(app.scopes, [])

    # A present, non-empty com.posthog.scopes that strips to nothing is rejected, not
    # stored as [] (which would widen the app to the broad UNPRIVILEGED default via the
    # empty-ceiling fallback). Mirrors DCR's all-stripped rejection; no app is created.
    @patch("posthog.api.oauth.cimd.requests.get")
    def test_all_non_grantable_scopes_on_creation_rejected(self, mock_get, _url_mock):
        only_non_grantable = [*sorted(PRIVILEGED_SCOPES), "not_a_real_scope:write"]
        mock_get.return_value = _mock_response(_make_metadata(com_posthog={"scopes": only_non_grantable}), headers={})

        with self.assertRaises(CIMDValidationError):
            fetch_and_upsert_cimd_application(VALID_CIMD_URL)

        self.assertFalse(OAuthApplication.objects.filter(cimd_metadata_url=VALID_CIMD_URL).exists())

    # On refresh, a doc whose scopes all strip out is rejected and the existing ceiling is
    # left untouched (fail-closed) rather than widened to the default.
    @patch("posthog.api.oauth.cimd.requests.get")
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
