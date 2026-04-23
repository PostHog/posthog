import json
import base64
import hashlib
from urllib.parse import urlencode

import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.core.cache import cache as real_cache
from django.test import override_settings

import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from rest_framework.test import APIClient

from posthog.api.oauth.cimd import (
    CIMD_PROVISIONING_ACCOUNT_REQUESTS_DEFAULT_RATE_LIMIT,
    CIMDFetchError,
    CIMDValidationError,
    _fetch_lock_key,
    fetch_and_upsert_cimd_application,
    fetch_cimd_metadata,
    get_application_by_client_id,
    get_or_create_cimd_application,
    get_or_create_cimd_provisioning_application,
    is_cimd_client_id,
    refresh_cimd_metadata_task,
    validate_cimd_url,
)
from posthog.models.oauth import OAuthApplication


def generate_rsa_key() -> str:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=4096)
    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return pem.decode("utf-8")


VALID_CIMD_URL = "https://app.example.com/.well-known/oauth-client-metadata.json"


def _make_metadata(url: str = VALID_CIMD_URL, **overrides) -> dict:
    metadata = {
        "client_id": url,
        "client_name": "Test MCP Client",
        "redirect_uris": ["http://127.0.0.1:3000/callback"],
        "grant_types": ["authorization_code"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
    }
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
@override_settings(
    OAUTH2_PROVIDER={
        **settings.OAUTH2_PROVIDER,
        "OIDC_RSA_PRIVATE_KEY": generate_rsa_key(),
    }
)
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
@override_settings(
    OAUTH2_PROVIDER={
        **settings.OAUTH2_PROVIDER,
        "OIDC_RSA_PRIVATE_KEY": generate_rsa_key(),
    }
)
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

    @patch("posthog.api.oauth.cimd.requests.get")
    def test_refresh_task_handles_fetch_failure_gracefully(self, mock_get, _url_mock):
        metadata = _make_metadata(client_name="Original Name")
        mock_get.return_value = _mock_response(metadata, headers={})
        fetch_and_upsert_cimd_application(VALID_CIMD_URL)

        mock_get.side_effect = requests.ConnectionError("DNS failed")
        refresh_cimd_metadata_task(VALID_CIMD_URL)

        app = OAuthApplication.objects.get(cimd_metadata_url=VALID_CIMD_URL)
        self.assertEqual(app.name, "Original Name")


@override_settings(
    OAUTH2_PROVIDER={
        **settings.OAUTH2_PROVIDER,
        "OIDC_RSA_PRIVATE_KEY": generate_rsa_key(),
    }
)
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
@override_settings(
    OAUTH2_PROVIDER={
        **settings.OAUTH2_PROVIDER,
        "OIDC_RSA_PRIVATE_KEY": generate_rsa_key(),
    }
)
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


@override_settings(
    OAUTH2_PROVIDER={
        **settings.OAUTH2_PROVIDER,
        "OIDC_RSA_PRIVATE_KEY": generate_rsa_key(),
    }
)
class TestAuthorizationServerMetadata(APIBaseTest):
    def test_advertises_cimd_support(self):
        client = APIClient()
        response = client.get("/.well-known/oauth-authorization-server")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data.get("client_id_metadata_document_supported"))


@override_settings(
    OAUTH2_PROVIDER={
        **settings.OAUTH2_PROVIDER,
        "OIDC_RSA_PRIVATE_KEY": generate_rsa_key(),
    }
)
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
