import time
from urllib.parse import urlencode

from django.core.cache import cache
from django.test import override_settings

from ee.api.agentic_provisioning import AUTH_CODE_CACHE_PREFIX
from ee.api.agentic_provisioning.signature import compute_signature
from ee.api.agentic_provisioning.test.base import HMAC_SECRET, StripeProvisioningTestBase


@override_settings(STRIPE_APP_SECRET_KEY=HMAC_SECRET)
class TestOAuthTokenExchange(StripeProvisioningTestBase):
    def _store_auth_code(self, code: str = "test_code", **overrides):
        data = {
            "user_id": self.user.id,
            "org_id": str(self.organization.id),
            "team_id": self.team.id,
            "stripe_account_id": "acct_123",
            "scopes": ["query:read", "project:read"],
            "region": "US",
        }
        data.update(overrides)
        cache.set(f"{AUTH_CODE_CACHE_PREFIX}{code}", data, timeout=300)
        return code

    def _token_request_body(self, **overrides):
        params = {"grant_type": "authorization_code", "code": "test_code"}
        params.update(overrides)
        return urlencode(params).encode()

    def _post_token(self, body: bytes):
        ts = int(time.time())
        sig = compute_signature(HMAC_SECRET, ts, body)
        return self.client.post(
            "/api/agentic/oauth/token",
            data=body,
            content_type="application/x-www-form-urlencoded",
            HTTP_STRIPE_SIGNATURE=f"t={ts},v1={sig}",
            HTTP_API_VERSION="0.1d",
        )

    def test_valid_code_exchange_returns_tokens(self):
        self._store_auth_code("test_code")
        body = self._token_request_body()
        res = self._post_token(body)
        assert res.status_code == 200
        data = res.json()
        assert data["token_type"] == "bearer"
        assert data["access_token"].startswith("pha_")
        assert data["refresh_token"].startswith("phr_")
        assert data["expires_in"] > 0
        assert "scope" not in data
        assert "account" in data
        assert data["account"]["id"] == str(self.organization.id)

    def test_invalid_code_returns_400(self):
        body = self._token_request_body(code="nonexistent")
        res = self._post_token(body)
        assert res.status_code == 400
        assert res.json()["error"] == "invalid_grant"

    def test_code_is_single_use(self):
        self._store_auth_code("single_use_code")
        body = self._token_request_body(code="single_use_code")
        res1 = self._post_token(body)
        assert res1.status_code == 200
        res2 = self._post_token(body)
        assert res2.status_code == 400

    def test_refresh_token_exchange(self):
        self._store_auth_code("code_for_refresh")
        body = self._token_request_body(code="code_for_refresh")
        first_res = self._post_token(body)
        refresh_token = first_res.json()["refresh_token"]

        refresh_body = urlencode({"grant_type": "refresh_token", "refresh_token": refresh_token}).encode()
        res = self._post_token(refresh_body)
        assert res.status_code == 200
        data = res.json()
        assert data["access_token"].startswith("pha_")
        assert data["refresh_token"].startswith("phr_")
        assert data["access_token"] != first_res.json()["access_token"]

    def test_invalid_refresh_token_returns_400(self):
        body = urlencode({"grant_type": "refresh_token", "refresh_token": "phr_invalid"}).encode()
        res = self._post_token(body)
        assert res.status_code == 400

    def test_unsupported_grant_type_returns_400(self):
        body = urlencode({"grant_type": "client_credentials"}).encode()
        res = self._post_token(body)
        assert res.status_code == 400

    def test_missing_code_returns_400(self):
        body = urlencode({"grant_type": "authorization_code"}).encode()
        res = self._post_token(body)
        assert res.status_code == 400

    def test_refresh_token_is_single_use(self):
        self._store_auth_code("code_for_replay")
        body = self._token_request_body(code="code_for_replay")
        first_res = self._post_token(body)
        refresh_token = first_res.json()["refresh_token"]

        refresh_body = urlencode({"grant_type": "refresh_token", "refresh_token": refresh_token}).encode()
        res1 = self._post_token(refresh_body)
        assert res1.status_code == 200

        res2 = self._post_token(refresh_body)
        assert res2.status_code == 400
        assert res2.json()["error"] == "invalid_grant"

    def test_missing_signature_returns_401(self):
        self._store_auth_code("test_code")
        body = self._token_request_body()
        res = self.client.post(
            "/api/agentic/oauth/token",
            data=body,
            content_type="application/x-www-form-urlencoded",
            HTTP_API_VERSION="0.1d",
        )
        assert res.status_code == 401
