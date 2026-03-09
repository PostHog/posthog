from unittest.mock import MagicMock, patch

from django.test import override_settings

from ee.api.agentic_provisioning.test.base import HMAC_SECRET, StripeProvisioningTestBase

MOCK_BILLING_PRODUCTS = {
    "products": [
        {
            "type": "product_analytics",
            "name": "Product analytics",
            "headline": "Product analytics with autocapture",
            "description": "A comprehensive product analytics platform.",
            "plans": [
                {"plan_key": "free-20230117", "price_id": None},
                {"plan_key": "paid-20240404", "price_id": "price_1PMG1IEuIatRXSdzht4rGlho"},
            ],
        },
        {
            "type": "session_replay",
            "name": "Session replay",
            "headline": "Watch how users experience your app",
            "description": "Session replay helps you diagnose issues.",
            "plans": [
                {"plan_key": "free-20231218", "price_id": None},
                {"plan_key": "paid-20240402-5k-free", "price_id": "price_1P1EZoEuIatRXSdzakl5PcUF"},
            ],
        },
        {
            "type": "platform_and_support",
            "name": "Platform and support",
            "description": "SSO, permission management, and support.",
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


@override_settings(STRIPE_APP_SECRET_KEY=HMAC_SECRET)
class TestProvisioningServices(StripeProvisioningTestBase):
    @patch("ee.api.agentic_provisioning.views.external_requests.get", return_value=_mock_billing_response())
    @patch("ee.api.agentic_provisioning.views.cache")
    def test_returns_services_from_billing(self, mock_cache, mock_get):
        mock_cache.get.return_value = None
        res = self._get_signed("/api/agentic/provisioning/services")
        assert res.status_code == 200
        data = res.json()
        service_ids = {s["id"] for s in data["data"]}
        assert "product_analytics" in service_ids
        assert "session_replay" in service_ids
        assert "platform_and_support" not in service_ids
        assert data["next_cursor"] == ""

    @patch("ee.api.agentic_provisioning.views.external_requests.get", return_value=_mock_billing_response())
    @patch("ee.api.agentic_provisioning.views.cache")
    def test_each_service_has_stripe_price(self, mock_cache, mock_get):
        mock_cache.get.return_value = None
        res = self._get_signed("/api/agentic/provisioning/services")
        assert res.status_code == 200
        for service in res.json()["data"]:
            assert service["pricing"]["type"] == "paid"
            assert service["pricing"]["paid"]["type"] == "stripe_price"
            assert service["pricing"]["paid"]["stripe_price"].startswith("price_")

    @patch("ee.api.agentic_provisioning.views.external_requests.get")
    @patch("ee.api.agentic_provisioning.views.cache")
    def test_uses_cache(self, mock_cache, mock_get):
        cached = [
            {
                "id": "product_analytics",
                "description": "cached",
                "categories": ["analytics"],
                "pricing": {"type": "paid", "paid": {"type": "stripe_price", "stripe_price": "price_cached"}},
            }
        ]
        mock_cache.get.return_value = cached
        res = self._get_signed("/api/agentic/provisioning/services")
        assert res.status_code == 200
        assert res.json()["data"][0]["pricing"]["paid"]["stripe_price"] == "price_cached"
        mock_get.assert_not_called()

    @patch("ee.api.agentic_provisioning.views.external_requests.get")
    @patch("ee.api.agentic_provisioning.views.cache")
    def test_billing_failure_returns_empty(self, mock_cache, mock_get):
        mock_cache.get.return_value = None
        mock_get.side_effect = Exception("connection error")
        res = self._get_signed("/api/agentic/provisioning/services")
        assert res.status_code == 200
        assert res.json()["data"] == []

    @patch("ee.api.agentic_provisioning.views.external_requests.get", return_value=_mock_billing_response())
    @patch("ee.api.agentic_provisioning.views.cache")
    def test_excludes_inclusion_only_products(self, mock_cache, mock_get):
        mock_cache.get.return_value = None
        res = self._get_signed("/api/agentic/provisioning/services")
        service_ids = {s["id"] for s in res.json()["data"]}
        assert "platform_and_support" not in service_ids

    def test_missing_signature_returns_401(self):
        res = self.client.get("/api/agentic/provisioning/services", HTTP_API_VERSION="0.1d")
        assert res.status_code == 401
