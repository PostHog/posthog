import time
from urllib.parse import urlencode

from django.core.cache import cache
from django.test import override_settings

from ee.api.agentic_provisioning.signature import compute_signature
from ee.api.agentic_provisioning.test.base import HMAC_SECRET, StripeProvisioningTestBase
from ee.api.agentic_provisioning.views import AUTH_CODE_CACHE_PREFIX


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
