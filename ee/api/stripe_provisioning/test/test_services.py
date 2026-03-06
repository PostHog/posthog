from django.test import override_settings

from ee.api.stripe_provisioning.test.base import HMAC_SECRET, StripeProvisioningTestBase


@override_settings(STRIPE_APP_SECRET_KEY=HMAC_SECRET)
class TestProvisioningServices(StripeProvisioningTestBase):
    def test_returns_service_catalog(self):
        res = self._get_signed("/api/agentic/provisioning/services")
        assert res.status_code == 200
        data = res.json()
        assert len(data["data"]) == 1
        service = data["data"][0]
        assert service["id"] == "posthog_analytics"
        assert "analytics" in service["categories"]
        assert data["next_cursor"] == ""

    def test_missing_signature_returns_401(self):
        res = self.client.get("/api/agentic/provisioning/services", HTTP_API_VERSION="0.1d")
        assert res.status_code == 401
