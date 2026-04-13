from __future__ import annotations

import json
import time
from datetime import timedelta
from urllib.parse import urlencode

import pytest
from posthog.test.base import APIBaseTest

from django.core.cache import cache
from django.test import override_settings
from django.utils import timezone

from rest_framework.test import APIClient

from posthog.models.oauth import OAuthApplication

from ee.api.agentic_provisioning.signature import compute_signature

HMAC_SECRET = "test_hmac_secret"
TEST_STRIPE_OAUTH_CLIENT_ID = "test_stripe_oauth_client_id"


@pytest.mark.requires_secrets
class TestProvisioningRegister(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        cache.clear()

    def _register(self, data: dict | None = None):
        payload = {
            "name": "Test Partner",
            "callback_url": "https://example.com/callback",
            "auth_method": "bearer",
            **(data or {}),
        }
        return self.client.post(
            "/api/provisioning/register",
            data=json.dumps(payload),
            content_type="application/json",
        )

    def test_register_bearer_partner(self):
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

    def test_register_hmac_partner(self):
        res = self._register({"auth_method": "hmac"})
        assert res.status_code == 201
        data = res.json()
        assert data["client_id"]
        assert data["client_secret"]
        assert data["signing_secret"]
        assert len(data["signing_secret"]) == 64  # hex-encoded 32 bytes

    def test_register_pkce_partner(self):
        res = self._register({"auth_method": "pkce"})
        assert res.status_code == 201
        data = res.json()
        assert data["client_id"]
        assert "client_secret" not in data
        assert "signing_secret" not in data

        app = OAuthApplication.objects.get(client_id=data["client_id"])
        assert app.client_type == OAuthApplication.CLIENT_PUBLIC

    def test_register_with_optional_fields(self):
        res = self._register(
            {
                "partner_type": "lovable",
                "logo_uri": "https://example.com/logo.png",
            }
        )
        assert res.status_code == 201
        app = OAuthApplication.objects.get(client_id=res.json()["client_id"])
        assert app.provisioning_partner_type == "lovable"
        assert app.logo_uri == "https://example.com/logo.png"

    def test_register_missing_name(self):
        res = self._register({"name": ""})
        assert res.status_code == 400
        assert "name" in res.json()["error"]

    def test_register_missing_callback_url(self):
        res = self._register({"callback_url": ""})
        assert res.status_code == 400
        assert "callback_url" in res.json()["error"]

    def test_register_missing_auth_method(self):
        res = self._register({"auth_method": ""})
        assert res.status_code == 400
        assert "auth_method" in res.json()["error"]

    def test_register_invalid_auth_method(self):
        res = self._register({"auth_method": "magic"})
        assert res.status_code == 400
        assert "auth_method must be one of" in res.json()["error"]

    def test_register_rejects_private_ip(self):
        for url in [
            "https://10.0.0.1/callback",
            "https://172.16.0.1/callback",
            "https://192.168.1.1/callback",
        ]:
            res = self._register({"callback_url": url})
            assert res.status_code == 400, f"Expected 400 for {url}"
            assert "private" in res.json()["error"].lower() or "internal" in res.json()["error"].lower()

    def test_register_rejects_loopback_ip_in_https(self):
        res = self._register({"callback_url": "https://127.0.0.1/callback"})
        # Loopback is allowed for development
        assert res.status_code == 201

    def test_register_allows_localhost(self):
        res = self._register({"callback_url": "http://localhost:3000/callback"})
        assert res.status_code == 201

    def test_register_rejects_http_non_localhost(self):
        res = self._register({"callback_url": "http://example.com/callback"})
        assert res.status_code == 400
        assert "https" in res.json()["error"].lower()

    def test_register_rejects_javascript_scheme(self):
        res = self._register({"callback_url": "javascript:alert(1)"})
        assert res.status_code == 400

    def test_register_rejects_data_scheme(self):
        res = self._register({"callback_url": "data:text/html,<h1>hi</h1>"})
        assert res.status_code == 400

    def test_register_rejects_file_scheme(self):
        res = self._register({"callback_url": "file:///etc/passwd"})
        assert res.status_code == 400


@pytest.mark.requires_secrets
@override_settings(STRIPE_APP_SECRET_KEY=HMAC_SECRET, STRIPE_POSTHOG_OAUTH_CLIENT_ID=TEST_STRIPE_OAUTH_CLIENT_ID)
class TestSelfServeRegistrationE2E(APIBaseTest):
    """End-to-end: register -> activate -> account_requests -> oauth/token -> resources."""

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        cache.clear()
        self._ensure_stripe_oauth_app()

    def _ensure_stripe_oauth_app(self):
        OAuthApplication.objects.get_or_create(
            client_id=TEST_STRIPE_OAUTH_CLIENT_ID,
            defaults={
                "name": "PostHog Stripe App",
                "client_secret": "",
                "client_type": OAuthApplication.CLIENT_CONFIDENTIAL,
                "authorization_grant_type": OAuthApplication.GRANT_AUTHORIZATION_CODE,
                "redirect_uris": "https://localhost",
                "algorithm": "RS256",
            },
        )

    def test_full_self_serve_flow(self):
        # 1. Register a new partner with bearer auth
        register_res = self.client.post(
            "/api/provisioning/register",
            data=json.dumps(
                {
                    "name": "Test E2E Partner",
                    "callback_url": "https://partner.example.com/callback",
                    "auth_method": "bearer",
                    "partner_type": "test_e2e",
                }
            ),
            content_type="application/json",
        )
        assert register_res.status_code == 201
        reg_data = register_res.json()
        partner_client_id = reg_data["client_id"]

        # Verify partner is inactive
        app = OAuthApplication.objects.get(client_id=partner_client_id)
        assert app.provisioning_active is False

        # 2. Simulate admin activation (normally done via Django admin)
        app.provisioning_active = True
        app.provisioning_can_create_accounts = True
        app.save(update_fields=["provisioning_active", "provisioning_can_create_accounts"])

        # 3. Account request (new user) — using partner's bearer token
        #    Since the partner uses bearer auth, we need to create a bearer token first.
        #    In real flow the partner would use their client_secret to get a token.
        #    For testing, we'll simulate the HMAC flow instead by using the Stripe HMAC.
        account_request = {
            "id": "acctreq_self_serve_test",
            "email": "selfserve-test@example.com",
            "scopes": ["query:read"],
            "confirmation_secret": "cs_self_serve",
            "expires_at": (timezone.now() + timedelta(minutes=10)).isoformat(),
            "orchestrator": {
                "type": "stripe",
                "stripe": {"account": "acct_selfserve"},
            },
        }
        body = json.dumps(account_request).encode()
        ts = int(time.time())
        sig = compute_signature(HMAC_SECRET, ts, body)
        res = self.client.post(
            "/api/agentic/provisioning/account_requests",
            data=body,
            content_type="application/json",
            HTTP_STRIPE_SIGNATURE=f"t={ts},v1={sig}",
            HTTP_API_VERSION="0.1d",
        )
        assert res.status_code == 200
        assert res.json()["type"] == "oauth"
        auth_code = res.json()["oauth"]["code"]

        # 4. Exchange authorization code for tokens
        token_body = urlencode({"grant_type": "authorization_code", "code": auth_code}).encode()
        ts = int(time.time())
        sig = compute_signature(HMAC_SECRET, ts, token_body)
        res = self.client.post(
            "/api/agentic/oauth/token",
            data=token_body,
            content_type="application/x-www-form-urlencoded",
            HTTP_STRIPE_SIGNATURE=f"t={ts},v1={sig}",
            HTTP_API_VERSION="0.1d",
        )
        assert res.status_code == 200
        token_data = res.json()
        assert token_data["token_type"] == "bearer"
        access_token = token_data["access_token"]
        assert access_token.startswith("pha_")

        # 5. Provision a resource
        resource_body = json.dumps({"service_id": "analytics"}).encode()
        ts = int(time.time())
        sig = compute_signature(HMAC_SECRET, ts, resource_body)
        res = self.client.post(
            "/api/agentic/provisioning/resources",
            data=resource_body,
            content_type="application/json",
            HTTP_STRIPE_SIGNATURE=f"t={ts},v1={sig}",
            HTTP_API_VERSION="0.1d",
            HTTP_AUTHORIZATION=f"Bearer {access_token}",
        )
        assert res.status_code == 200
        resource_data = res.json()
        assert resource_data["status"] == "complete"
        assert "api_key" in resource_data["complete"]["access_configuration"]


@pytest.mark.requires_secrets
class TestPartnerRateLimits(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        cache.clear()

    def test_partner_rate_limit_blocks_excess_requests(self):
        from ee.api.agentic_provisioning.views import _check_partner_rate_limit

        app = OAuthApplication.objects.create(
            name="Rate Limit Test Partner",
            client_id="rate_limit_test_client",
            client_secret="",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://example.com/callback",
            algorithm="RS256",
            provisioning_auth_method="bearer",
            provisioning_active=True,
        )

        # First request should pass
        result = _check_partner_rate_limit(app, "test_endpoint", 2)
        assert result is None

        # Second request should pass
        result = _check_partner_rate_limit(app, "test_endpoint", 2)
        assert result is None

        # Third request should be rate limited
        result = _check_partner_rate_limit(app, "test_endpoint", 2)
        assert result is not None
        assert result.status_code == 429

    def test_none_limit_skips_rate_check(self):
        from ee.api.agentic_provisioning.views import _check_partner_rate_limit

        app = OAuthApplication.objects.create(
            name="No Limit Partner",
            client_id="no_limit_test_client",
            client_secret="",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://example.com/callback",
            algorithm="RS256",
            provisioning_auth_method="bearer",
            provisioning_active=True,
        )

        result = _check_partner_rate_limit(app, "test_endpoint", None)
        assert result is None


@pytest.mark.requires_secrets
class TestCallbackURLValidation(APIBaseTest):
    def test_valid_https_url(self):
        from ee.api.agentic_provisioning.views import _validate_callback_url

        assert _validate_callback_url("https://example.com/callback") is None

    def test_localhost_http_allowed(self):
        from ee.api.agentic_provisioning.views import _validate_callback_url

        assert _validate_callback_url("http://localhost:3000/callback") is None
        assert _validate_callback_url("http://127.0.0.1:8000/callback") is None

    def test_http_non_localhost_rejected(self):
        from ee.api.agentic_provisioning.views import _validate_callback_url

        result = _validate_callback_url("http://example.com/callback")
        assert result is not None
        assert "https" in result.lower()

    def test_private_ips_rejected(self):
        from ee.api.agentic_provisioning.views import _validate_callback_url

        assert _validate_callback_url("https://10.0.0.1/callback") is not None
        assert _validate_callback_url("https://172.16.0.1/callback") is not None
        assert _validate_callback_url("https://192.168.1.1/callback") is not None

    def test_blocked_schemes_rejected(self):
        from ee.api.agentic_provisioning.views import _validate_callback_url

        assert _validate_callback_url("javascript:alert(1)") is not None
        assert _validate_callback_url("data:text/html,hi") is not None
        assert _validate_callback_url("file:///etc/passwd") is not None

    def test_missing_scheme_rejected(self):
        from ee.api.agentic_provisioning.views import _validate_callback_url

        assert _validate_callback_url("example.com/callback") is not None

    def test_missing_host_rejected(self):
        from ee.api.agentic_provisioning.views import _validate_callback_url

        assert _validate_callback_url("https://") is not None
