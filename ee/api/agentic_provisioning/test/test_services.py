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

CACHED_SERVICES = [
    {
        "id": "posthog",
        "description": "PostHog",
        "categories": ["analytics"],
        "pricing": {"type": "free"},
    },
    {
        "id": "product_analytics",
        "description": "cached",
        "categories": ["analytics"],
        "pricing": {
            "type": "component",
            "component": {
                "options": [
                    {
                        "parent_service_ids": ["posthog"],
                        "type": "paid",
                        "paid": {"type": "stripe_price", "stripe_price": "price_cached"},
                    }
                ]
            },
        },
    },
]


def _mock_billing_response():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = MOCK_BILLING_PRODUCTS
    mock_resp.raise_for_status.return_value = None
    return mock_resp


def _mock_cache_expired():
    """Cache with data but expired (expires_at in the past)."""
    store = {
        SERVICES_CACHE_KEY: CACHED_SERVICES,
        SERVICES_CACHE_EXPIRES_KEY: time.time() - 10,
    }
    mock = MagicMock()
    mock.get.side_effect = lambda key: store.get(key)
    return mock


def _mock_cache_fresh():
    """Cache with data and still fresh."""
    store = {
        SERVICES_CACHE_KEY: CACHED_SERVICES,
        SERVICES_CACHE_EXPIRES_KEY: time.time() + 3600,
    }
    mock = MagicMock()
    mock.get.side_effect = lambda key: store.get(key)
    return mock


def _mock_cache_empty():
    """No cached data at all."""
    mock = MagicMock()
    mock.get.return_value = None
    return mock


@override_settings(STRIPE_APP_SECRET_KEY=HMAC_SECRET)
class TestProvisioningServices(StripeProvisioningTestBase):
    @patch("ee.api.agentic_provisioning.views.external_requests.get", return_value=_mock_billing_response())
    @patch("ee.api.agentic_provisioning.views.cache", new_callable=_mock_cache_empty)
    def test_returns_parent_posthog_service(self, mock_cache, mock_get):
        res = self._get_signed("/api/agentic/provisioning/services")
        assert res.status_code == 200
        data = res.json()
        services = data["data"]
        parent = services[0]
        assert parent["id"] == "posthog"
        assert parent["pricing"]["type"] == "free"
        assert "analytics" in parent["categories"]
        assert data["next_cursor"] == ""

    @patch("ee.api.agentic_provisioning.views.external_requests.get", return_value=_mock_billing_response())
    @patch("ee.api.agentic_provisioning.views.cache", new_callable=_mock_cache_empty)
    def test_returns_component_services_from_billing(self, mock_cache, mock_get):
        res = self._get_signed("/api/agentic/provisioning/services")
        assert res.status_code == 200
        data = res.json()
        service_ids = {s["id"] for s in data["data"]}
        assert "posthog" in service_ids
        assert "product_analytics" in service_ids
        assert "session_replay" in service_ids

    @patch("ee.api.agentic_provisioning.views.external_requests.get", return_value=_mock_billing_response())
    @patch("ee.api.agentic_provisioning.views.cache", new_callable=_mock_cache_empty)
    def test_component_services_have_parent_and_stripe_price(self, mock_cache, mock_get):
        res = self._get_signed("/api/agentic/provisioning/services")
        assert res.status_code == 200
        component_services = [s for s in res.json()["data"] if s["id"] != "posthog"]
        assert len(component_services) > 0
        for service in component_services:
            assert service["pricing"]["type"] == "component"
            options = service["pricing"]["component"]["options"]
            assert len(options) == 1
            assert options[0]["parent_service_ids"] == ["posthog"]
            assert options[0]["type"] == "paid"
            assert options[0]["paid"]["type"] == "stripe_price"
            assert options[0]["paid"]["stripe_price"].startswith("price_")

    @patch("ee.api.agentic_provisioning.views.external_requests.get")
    @patch("ee.api.agentic_provisioning.views.cache", new_callable=_mock_cache_fresh)
    def test_uses_fresh_cache(self, mock_cache, mock_get):
        res = self._get_signed("/api/agentic/provisioning/services")
        assert res.status_code == 200
        component = res.json()["data"][1]
        assert component["pricing"]["component"]["options"][0]["paid"]["stripe_price"] == "price_cached"
        mock_get.assert_not_called()

    @patch("ee.api.agentic_provisioning.views.external_requests.get")
    @patch("ee.api.agentic_provisioning.views.cache", new_callable=_mock_cache_empty)
    def test_billing_failure_no_cache_returns_parent_only(self, mock_cache, mock_get):
        mock_get.side_effect = Exception("connection error")
        res = self._get_signed("/api/agentic/provisioning/services")
        assert res.status_code == 200
        data = res.json()["data"]
        assert len(data) == 1
        assert data[0]["id"] == "posthog"

    @patch("ee.api.agentic_provisioning.views.external_requests.get")
    @patch("ee.api.agentic_provisioning.views.cache", new_callable=_mock_cache_expired)
    def test_billing_failure_serves_stale_cache(self, mock_cache, mock_get):
        mock_get.side_effect = Exception("connection error")
        res = self._get_signed("/api/agentic/provisioning/services")
        assert res.status_code == 200
        data = res.json()["data"]
        assert len(data) == 2
        assert data[0]["id"] == "posthog"
        assert data[1]["id"] == "product_analytics"

    @patch("ee.api.agentic_provisioning.views.external_requests.get", return_value=_mock_billing_response())
    @patch("ee.api.agentic_provisioning.views.cache", new_callable=_mock_cache_empty)
    def test_excludes_inclusion_only_products(self, mock_cache, mock_get):
        res = self._get_signed("/api/agentic/provisioning/services")
        service_ids = {s["id"] for s in res.json()["data"]}
        assert "platform_and_support" not in service_ids

    def test_missing_signature_returns_401(self):
        res = self.client.get("/api/agentic/provisioning/services", HTTP_API_VERSION="0.1d")
        assert res.status_code == 401
