import time

from unittest.mock import MagicMock, patch

from django.test import override_settings

from ee.api.agentic_provisioning.test.base import HMAC_SECRET, StripeProvisioningTestBase
from ee.api.agentic_provisioning.views import SERVICES_CACHE_EXPIRES_KEY, SERVICES_CACHE_KEY

MOCK_BILLING_PRODUCTS = {
    "products": [
        {
            "type": "product_analytics",
            "name": "Product analytics",
            "headline": "Product analytics with autocapture",
            "plans": [
                {"plan_key": "free-20230117", "price_id": None},
                {"plan_key": "paid-20240404", "price_id": "price_1PMG1IEuIatRXSdzht4rGlho"},
            ],
        },
        {
            "type": "session_replay",
            "name": "Session replay",
            "headline": "Watch how users experience your app",
            "plans": [
                {"plan_key": "free-20231218", "price_id": None},
                {"plan_key": "paid-20240402-5k-free", "price_id": "price_1P1EZoEuIatRXSdzakl5PcUF"},
            ],
        },
        {
            "type": "platform_and_support",
            "name": "Platform and support",
            "inclusion_only": True,
            "plans": [{"plan_key": "free-20230117", "price_id": None}],
        },
    ]
}


def _mock_billing_response():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = MOCK_BILLING_PRODUCTS
    mock_resp.raise_for_status.return_value = None
    return mock_resp


def _mock_cache_empty():
    mock = MagicMock()
    mock.get.return_value = None
    return mock


def _mock_cache_fresh(services):
    store = {
        SERVICES_CACHE_KEY: services,
        SERVICES_CACHE_EXPIRES_KEY: time.time() + 3600,
    }
    mock = MagicMock()
    mock.get.side_effect = lambda key: store.get(key)
    return mock


@override_settings(STRIPE_APP_SECRET_KEY=HMAC_SECRET)
class TestProvisioningServices(StripeProvisioningTestBase):
    @patch("ee.api.agentic_provisioning.views.requests.get", return_value=_mock_billing_response())
    @patch("ee.api.agentic_provisioning.views.cache", new_callable=_mock_cache_empty)
    def test_returns_three_services(self, mock_cache, mock_get):
        res = self._get_signed("/api/agentic/provisioning/services")
        assert res.status_code == 200
        data = res.json()
        services = data["data"]
        assert len(services) == 3
        assert "next_cursor" not in data
        ids = [s["id"] for s in services]
        assert ids == ["free", "pay_as_you_go", "analytics"]

    @patch("ee.api.agentic_provisioning.views.requests.get", return_value=_mock_billing_response())
    @patch("ee.api.agentic_provisioning.views.cache", new_callable=_mock_cache_empty)
    def test_analytics_deployable_description_from_billing(self, mock_cache, mock_get):
        res = self._get_signed("/api/agentic/provisioning/services")
        analytics = res.json()["data"][2]
        assert analytics["id"] == "analytics"
        assert analytics["kind"] == "deployable"
        assert "product analytics" in analytics["description"]
        assert "session replay" in analytics["description"]
        assert "platform and support" not in analytics["description"].lower()

    @patch("ee.api.agentic_provisioning.views.requests.get", return_value=_mock_billing_response())
    @patch("ee.api.agentic_provisioning.views.cache", new_callable=_mock_cache_empty)
    def test_analytics_deployable_allows_service_ref_updates(self, mock_cache, mock_get):
        res = self._get_signed("/api/agentic/provisioning/services")
        analytics = res.json()["data"][2]
        assert analytics["allowed_updates"] == ["service_ref"]

    @patch("ee.api.agentic_provisioning.views.requests.get", return_value=_mock_billing_response())
    @patch("ee.api.agentic_provisioning.views.cache", new_callable=_mock_cache_empty)
    def test_free_plan_can_upgrade_to_pay_as_you_go(self, mock_cache, mock_get):
        res = self._get_signed("/api/agentic/provisioning/services")
        free = res.json()["data"][0]
        assert free["id"] == "free"
        assert free["allowed_updates"] == ["pay_as_you_go"]

    @patch("ee.api.agentic_provisioning.views.requests.get", return_value=_mock_billing_response())
    @patch("ee.api.agentic_provisioning.views.cache", new_callable=_mock_cache_empty)
    def test_pay_as_you_go_plan_can_downgrade_to_free(self, mock_cache, mock_get):
        res = self._get_signed("/api/agentic/provisioning/services")
        payg = res.json()["data"][1]
        assert payg["id"] == "pay_as_you_go"
        assert payg["allowed_updates"] == ["free"]

    @patch("ee.api.agentic_provisioning.views.requests.get", return_value=_mock_billing_response())
    @patch("ee.api.agentic_provisioning.views.cache", new_callable=_mock_cache_empty)
    def test_pay_as_you_go_pricing_includes_rates(self, mock_cache, mock_get):
        res = self._get_signed("/api/agentic/provisioning/services")
        payg = res.json()["data"][1]
        freeform = payg["pricing"]["paid"]["freeform"]
        assert "$0/mo base" in freeform
        assert "posthog.com/pricing" in freeform

    @patch("ee.api.agentic_provisioning.views.requests.get", return_value=_mock_billing_response())
    @patch("ee.api.agentic_provisioning.views.cache", new_callable=_mock_cache_empty)
    def test_analytics_deployable_has_component_pricing(self, mock_cache, mock_get):
        res = self._get_signed("/api/agentic/provisioning/services")
        analytics = res.json()["data"][2]
        assert analytics["pricing"]["type"] == "component"
        options = analytics["pricing"]["component"]["options"]
        assert len(options) == 2
        assert options[0]["parent_service_ids"] == ["free"]
        assert options[0]["type"] == "free"
        assert options[1]["parent_service_ids"] == ["pay_as_you_go"]
        assert options[1]["type"] == "paid"

    @patch("ee.api.agentic_provisioning.views.requests.get")
    @patch("ee.api.agentic_provisioning.views.cache", new_callable=_mock_cache_empty)
    def test_billing_failure_returns_fallback(self, mock_cache, mock_get):
        mock_get.side_effect = Exception("connection error")
        res = self._get_signed("/api/agentic/provisioning/services")
        assert res.status_code == 200
        data = res.json()["data"]
        assert len(data) == 3
        ids = [s["id"] for s in data]
        assert ids == ["free", "pay_as_you_go", "analytics"]
        assert "PostHog" in data[2]["description"]

    @patch("ee.api.agentic_provisioning.views.requests.get", return_value=_mock_billing_response())
    @patch("ee.api.agentic_provisioning.views.cache", new_callable=_mock_cache_empty)
    def test_all_services_have_categories(self, mock_cache, mock_get):
        res = self._get_signed("/api/agentic/provisioning/services")
        for service in res.json()["data"]:
            assert "analytics" in service["categories"]

    def test_missing_signature_returns_401(self):
        res = self.client.get("/api/agentic/provisioning/services", HTTP_API_VERSION="0.1d")
        assert res.status_code == 401
