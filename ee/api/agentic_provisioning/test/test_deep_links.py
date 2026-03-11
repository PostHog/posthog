import time
from urllib.parse import urlencode

from django.core.cache import cache
from django.test import override_settings

from ee.api.agentic_provisioning.signature import compute_signature
from ee.api.agentic_provisioning.test.base import HMAC_SECRET, StripeProvisioningTestBase
from ee.api.agentic_provisioning.views import AUTH_CODE_CACHE_PREFIX, DEEP_LINK_CACHE_PREFIX


@override_settings(STRIPE_APP_SECRET_KEY=HMAC_SECRET)
class TestDeepLinks(StripeProvisioningTestBase):
    def _get_bearer_token(self) -> str:
        code = "dl_test_code"
        cache.set(
            f"{AUTH_CODE_CACHE_PREFIX}{code}",
            {
                "user_id": self.user.id,
                "org_id": str(self.organization.id),
                "team_id": self.team.id,
                "stripe_account_id": "acct_123",
                "scopes": ["query:read"],
                "region": "US",
            },
            timeout=300,
        )
        body = urlencode({"grant_type": "authorization_code", "code": code}).encode()
        ts = int(time.time())
        sig = compute_signature(HMAC_SECRET, ts, body)
        res = self.client.post(
            "/api/agentic/oauth/token",
            data=body,
            content_type="application/x-www-form-urlencoded",
            HTTP_STRIPE_SIGNATURE=f"t={ts},v1={sig}",
            HTTP_API_VERSION="0.1d",
        )
        return res.json()["access_token"]

    def test_deep_link_returns_url(self):
        token = self._get_bearer_token()
        res = self._post_signed_with_bearer(
            "/api/agentic/provisioning/deep_links",
            data={"purpose": "dashboard"},
            token=token,
        )
        assert res.status_code == 200
        data = res.json()
        assert data["purpose"] == "dashboard"
        assert "url" in data
        assert "expires_at" in data
        assert "token=" in data["url"]

    def test_deep_link_url_contains_team_id(self):
        token = self._get_bearer_token()
        res = self._post_signed_with_bearer(
            "/api/agentic/provisioning/deep_links",
            data={"purpose": "dashboard"},
            token=token,
        )
        url = res.json()["url"]
        assert f"team_id={self.team.id}" in url

    def test_deep_link_missing_bearer_returns_401(self):
        res = self._post_signed("/api/agentic/provisioning/deep_links", data={"purpose": "dashboard"})
        assert res.status_code == 401


@override_settings(STRIPE_APP_SECRET_KEY=HMAC_SECRET)
class TestStripeLogin(StripeProvisioningTestBase):
    def _create_deep_link_token(self) -> str:
        token = "test_deep_link_token"
        cache.set(
            f"{DEEP_LINK_CACHE_PREFIX}{token}",
            {"user_id": self.user.id, "team_id": self.team.id},
            timeout=600,
        )
        return token

    def test_valid_token_logs_in_and_redirects_to_project(self):
        token = self._create_deep_link_token()
        res = self.client.get(f"/login/stripe?token={token}")
        assert res.status_code == 302
        assert f"/project/{self.team.id}" in res.url

    def test_valid_token_creates_session(self):
        token = self._create_deep_link_token()
        self.client.get(f"/login/stripe?token={token}")
        res = self.client.get("/api/users/@me/")
        assert res.status_code == 200
        assert res.json()["email"] == self.user.email

    def test_token_is_single_use(self):
        token = self._create_deep_link_token()
        res1 = self.client.get(f"/login/stripe?token={token}")
        assert res1.status_code == 302
        assert "/project/" in res1.url
        res2 = self.client.get(f"/login/stripe?token={token}")
        assert res2.status_code == 302
        assert "expired_or_invalid_token" in res2.url

    def test_missing_token_redirects_with_error(self):
        res = self.client.get("/login/stripe")
        assert res.status_code == 302
        assert "missing_token" in res.url

    def test_invalid_token_redirects_with_error(self):
        res = self.client.get("/login/stripe?token=bogus")
        assert res.status_code == 302
        assert "expired_or_invalid_token" in res.url

    def test_without_team_id_redirects_to_root(self):
        token = "test_no_team_token"
        cache.set(
            f"{DEEP_LINK_CACHE_PREFIX}{token}",
            {"user_id": self.user.id, "team_id": None},
            timeout=600,
        )
        res = self.client.get(f"/login/stripe?token={token}")
        assert res.status_code == 302
        assert res.url == "/"
