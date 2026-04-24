from __future__ import annotations

import json

import pytest
from posthog.test.base import APIBaseTest

from django.conf import settings
from django.core.cache import cache
from django.test import override_settings

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from rest_framework.test import APIClient

from posthog.models.oauth import OAuthApplication

from ee.api.agentic_provisioning.registration import _validate_callback_url


def _generate_rsa_key() -> str:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return pem.decode("utf-8")


_RSA_KEY = _generate_rsa_key()


@pytest.mark.requires_secrets
@override_settings(
    OIDC_RSA_PRIVATE_KEY=_RSA_KEY,
    OAUTH2_PROVIDER={**settings.OAUTH2_PROVIDER, "OIDC_RSA_PRIVATE_KEY": _RSA_KEY},
)
class TestProvisioningRegister(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.client = APIClient()
        cache.clear()

    def _register(self, overrides: dict | None = None):
        payload = {
            "name": "Test Partner",
            "callback_url": "https://example.com/callback",
            "auth_method": "bearer",
            **(overrides or {}),
        }
        return self.client.post(
            "/api/provisioning/register",
            data=json.dumps(payload),
            content_type="application/json",
        )

    def test_register_bearer_partner(self) -> None:
        res = self._register()
        assert res.status_code == 201
        data = res.json()
        assert data["client_id"]
        assert data["client_secret"]
        assert data["auth_method"] == "bearer"
        assert data["provisioning_active"] is False
        assert "signing_secret" not in data

        app = OAuthApplication.objects.get(client_id=data["client_id"])
        assert app.provisioning_auth_method == "bearer"
        assert app.provisioning_active is False
        assert app.provisioning_can_create_accounts is False
        assert app.redirect_uris == "https://example.com/callback"
        assert app.client_type == OAuthApplication.CLIENT_CONFIDENTIAL

    def test_register_hmac_partner_returns_signing_secret(self) -> None:
        res = self._register({"auth_method": "hmac"})
        assert res.status_code == 201
        data = res.json()
        assert data["client_id"]
        assert data["client_secret"]
        assert data["signing_secret"]
        assert len(data["signing_secret"]) == 64

        app = OAuthApplication.objects.get(client_id=data["client_id"])
        assert app.provisioning_auth_method == "hmac"
        assert app.provisioning_signing_secret == data["signing_secret"]

    def test_register_rejects_pkce(self) -> None:
        res = self._register({"auth_method": "pkce"})
        assert res.status_code == 400
        assert "auth_method must be one of" in res.json()["error"]

    def test_register_with_optional_fields(self) -> None:
        res = self._register(
            {
                "partner_type": "acme",
                "logo_uri": "https://example.com/logo.png",
            }
        )
        assert res.status_code == 201
        app = OAuthApplication.objects.get(client_id=res.json()["client_id"])
        assert app.provisioning_partner_type == "acme"
        assert app.logo_uri == "https://example.com/logo.png"

    def test_register_missing_name(self) -> None:
        res = self._register({"name": ""})
        assert res.status_code == 400
        assert "name" in res.json()["error"]

    def test_register_missing_callback_url(self) -> None:
        res = self._register({"callback_url": ""})
        assert res.status_code == 400
        assert "callback_url" in res.json()["error"]

    def test_register_missing_auth_method(self) -> None:
        res = self._register({"auth_method": ""})
        assert res.status_code == 400
        assert "auth_method" in res.json()["error"]

    def test_register_invalid_auth_method(self) -> None:
        res = self._register({"auth_method": "magic"})
        assert res.status_code == 400
        assert "auth_method must be one of" in res.json()["error"]

    def test_register_rejects_private_ip(self) -> None:
        for url in [
            "https://10.0.0.1/callback",
            "https://172.16.0.1/callback",
            "https://192.168.1.1/callback",
        ]:
            res = self._register({"callback_url": url})
            assert res.status_code == 400, f"Expected 400 for {url}"
            assert "private" in res.json()["error"].lower() or "internal" in res.json()["error"].lower()

    def test_register_allows_localhost_http(self) -> None:
        res = self._register({"callback_url": "http://localhost:3000/callback"})
        assert res.status_code == 201

    def test_register_rejects_http_non_localhost(self) -> None:
        res = self._register({"callback_url": "http://example.com/callback"})
        assert res.status_code == 400
        assert "https" in res.json()["error"].lower()

    def test_register_rejects_dangerous_schemes(self) -> None:
        for url in ["javascript:alert(1)", "data:text/html,<h1>hi</h1>", "file:///etc/passwd"]:
            res = self._register({"callback_url": url})
            assert res.status_code == 400, f"Expected 400 for {url}"


class TestCallbackURLValidation(APIBaseTest):
    def test_valid_https_url(self) -> None:
        assert _validate_callback_url("https://example.com/callback") is None

    def test_localhost_http_allowed(self) -> None:
        assert _validate_callback_url("http://localhost:3000/callback") is None
        assert _validate_callback_url("http://127.0.0.1:8000/callback") is None

    def test_http_non_localhost_rejected(self) -> None:
        result = _validate_callback_url("http://example.com/callback")
        assert result is not None
        assert "https" in result.lower()

    def test_private_ips_rejected(self) -> None:
        assert _validate_callback_url("https://10.0.0.1/callback") is not None
        assert _validate_callback_url("https://172.16.0.1/callback") is not None
        assert _validate_callback_url("https://192.168.1.1/callback") is not None

    def test_blocked_schemes_rejected(self) -> None:
        assert _validate_callback_url("javascript:alert(1)") is not None
        assert _validate_callback_url("data:text/html,hi") is not None
        assert _validate_callback_url("file:///etc/passwd") is not None

    def test_missing_scheme_rejected(self) -> None:
        assert _validate_callback_url("example.com/callback") is not None

    def test_missing_host_rejected(self) -> None:
        assert _validate_callback_url("https://") is not None
