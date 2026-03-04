import time
from urllib.parse import urlencode

from django.core.cache import cache
from django.test import override_settings

from ee.api.agentic_provisioning.signature import compute_signature
from ee.api.agentic_provisioning.test.base import HMAC_SECRET, StripeProvisioningTestBase
from ee.api.agentic_provisioning.views import AUTH_CODE_CACHE_PREFIX


@override_settings(STRIPE_APP_SECRET_KEY=HMAC_SECRET)
class TestProvisioningResources(StripeProvisioningTestBase):
    def _get_bearer_token(self) -> str:
        code = "res_test_code"
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

    def test_create_resource_returns_complete(self):
        token = self._get_bearer_token()
        res = self._post_signed_with_bearer(
            "/api/agentic/provisioning/resources",
            data={"service_id": "posthog_analytics"},
            token=token,
        )
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "complete"
        assert data["id"] == str(self.team.id)
        assert "api_key" in data["complete"]["access_configuration"]
        assert "host" in data["complete"]["access_configuration"]

    def test_get_resource_returns_complete(self):
        token = self._get_bearer_token()
        res = self._get_signed_with_bearer(
            f"/api/agentic/provisioning/resources/{self.team.id}",
            token=token,
        )
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "complete"
        assert data["id"] == str(self.team.id)

    def test_get_resource_wrong_team_returns_403(self):
        token = self._get_bearer_token()
        res = self._get_signed_with_bearer(
            "/api/agentic/provisioning/resources/99999",
            token=token,
        )
        assert res.status_code == 403

    def test_get_resource_invalid_id_returns_400(self):
        token = self._get_bearer_token()
        res = self._get_signed_with_bearer(
            "/api/agentic/provisioning/resources/not-a-number",
            token=token,
        )
        assert res.status_code == 400

    def test_create_resource_missing_bearer_returns_401(self):
        res = self._post_signed("/api/agentic/provisioning/resources", data={"service_id": "posthog_analytics"})
        assert res.status_code == 401

    def test_create_resource_invalid_bearer_returns_401(self):
        res = self._post_signed_with_bearer(
            "/api/agentic/provisioning/resources",
            data={"service_id": "posthog_analytics"},
            token="pha_invalid_token",
        )
        assert res.status_code == 401

    def test_get_resource_missing_bearer_returns_401(self):
        res = self._get_signed(f"/api/agentic/provisioning/resources/{self.team.id}")
        assert res.status_code == 401
