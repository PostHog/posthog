from django.test import override_settings

from ee.api.agentic_provisioning.test.base import HMAC_SECRET, StripeProvisioningTestBase


@override_settings(STRIPE_APP_SECRET_KEY=HMAC_SECRET)
class TestProvisioningServices(StripeProvisioningTestBase):
    def test_returns_analytics_and_pay_as_you_go_services(self):
        res = self._get_signed("/api/agentic/provisioning/services")
        assert res.status_code == 200
        data = res.json()
        services = data["data"]
        assert len(services) == 2
        assert data["next_cursor"] == ""

        parent = services[0]
        assert parent["id"] == "analytics"
        assert parent["pricing"]["type"] == "free"
        assert set(parent["categories"]) == {"analytics", "feature_flags", "ai"}

        paid = services[1]
        assert paid["id"] == "pay_as_you_go"
        assert paid["pricing"]["type"] == "component"
        options = paid["pricing"]["component"]["options"]
        assert len(options) == 1
        assert options[0]["parent_service_ids"] == ["analytics"]
        assert options[0]["type"] == "paid"

    def test_missing_signature_returns_401(self):
        res = self.client.get("/api/agentic/provisioning/services", HTTP_API_VERSION="0.1d")
        assert res.status_code == 401
