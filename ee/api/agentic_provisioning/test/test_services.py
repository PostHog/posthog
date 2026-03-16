from django.test import override_settings

from ee.api.agentic_provisioning.test.base import HMAC_SECRET, StripeProvisioningTestBase


@override_settings(STRIPE_APP_SECRET_KEY=HMAC_SECRET)
class TestProvisioningServices(StripeProvisioningTestBase):
    def test_returns_single_analytics_service(self):
        res = self._get_signed("/api/agentic/provisioning/services")
        assert res.status_code == 200
        data = res.json()
        services = data["data"]
        assert len(services) == 1
        service = services[0]
        assert service["id"] == "analytics"
        assert service["pricing"]["type"] == "free"
        assert "analytics" in service["categories"]
        assert "feature_flags" in service["categories"]
        assert "ai" in service["categories"]
        assert data["next_cursor"] == ""

    def test_missing_signature_returns_401(self):
        res = self.client.get("/api/agentic/provisioning/services", HTTP_API_VERSION="0.1d")
        assert res.status_code == 401
