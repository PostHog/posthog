from django.test import override_settings

from ee.api.agentic_provisioning.test.base import HMAC_SECRET, StripeProvisioningTestBase


@override_settings(STRIPE_APP_SECRET_KEY=HMAC_SECRET)
class TestProvisioningServices(StripeProvisioningTestBase):
    def test_returns_three_services(self):
        res = self._get_signed("/api/agentic/provisioning/services")
        assert res.status_code == 200
        data = res.json()
        services = data["data"]
        assert len(services) == 3
        assert data["next_cursor"] == ""

    def test_free_plan(self):
        res = self._get_signed("/api/agentic/provisioning/services")
        free = res.json()["data"][0]
        assert free["id"] == "free"
        assert free["kind"] == "plan"
        assert free["pricing"]["type"] == "free"

    def test_pay_as_you_go_plan(self):
        res = self._get_signed("/api/agentic/provisioning/services")
        paid = res.json()["data"][1]
        assert paid["id"] == "pay_as_you_go"
        assert paid["kind"] == "plan"
        assert paid["pricing"]["type"] == "paid"

    def test_analytics_deployable(self):
        res = self._get_signed("/api/agentic/provisioning/services")
        analytics = res.json()["data"][2]
        assert analytics["id"] == "analytics"
        assert analytics["kind"] == "deployable"
        assert analytics["pricing"]["type"] == "component"
        options = analytics["pricing"]["component"]["options"]
        assert len(options) == 2
        assert options[0]["parent_service_ids"] == ["free"]
        assert options[0]["type"] == "free"
        assert options[1]["parent_service_ids"] == ["pay_as_you_go"]
        assert options[1]["type"] == "paid"

    def test_all_services_have_categories(self):
        res = self._get_signed("/api/agentic/provisioning/services")
        for service in res.json()["data"]:
            assert "analytics" in service["categories"]

    def test_missing_signature_returns_401(self):
        res = self.client.get("/api/agentic/provisioning/services", HTTP_API_VERSION="0.1d")
        assert res.status_code == 401
