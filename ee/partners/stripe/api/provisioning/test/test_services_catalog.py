from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import TestCase

from ee.partners.stripe.api.provisioning.constants import (
    ANALYTICS_SERVICE_ID,
    FREE_PLAN_SERVICE_ID,
    PAY_AS_YOU_GO_SERVICE_ID,
    SERVICES_CACHE_EXPIRES_KEY,
)
from ee.partners.stripe.api.provisioning.services_catalog import _FALLBACK_DESCRIPTION, get_services


def _billing_response(products: list[dict]) -> MagicMock:
    res = MagicMock()
    res.json.return_value = {"products": products}
    res.raise_for_status.return_value = None
    return res


class TestServicesCatalog(TestCase):
    def setUp(self):
        super().setUp()
        cache.clear()

    def test_catalog_built_from_billing_products_filters_and_lists_names(self):
        products: list[dict] = [
            {"name": "Product analytics", "type": "product_analytics"},
            {"name": "Session replay", "type": "session_replay"},
            {"name": "Support", "type": "platform_and_support"},
            {"name": "Data pipelines", "type": "integrations"},
            {"name": "Add-on", "type": "product_analytics", "inclusion_only": True},
        ]
        with patch(
            "ee.partners.stripe.api.provisioning.services_catalog.requests.get",
            return_value=_billing_response(products),
        ):
            services = get_services()

        by_id = {s["id"]: s for s in services}
        assert set(by_id) == {FREE_PLAN_SERVICE_ID, PAY_AS_YOU_GO_SERVICE_ID, ANALYTICS_SERVICE_ID}
        # Excluded types and inclusion_only entries drop out; the rest are lowercased into the blurb.
        assert by_id[ANALYTICS_SERVICE_ID]["description"] == "PostHog — product analytics, session replay, and more."

    def test_stale_cache_served_when_billing_fetch_fails(self):
        products = [{"name": "Product analytics", "type": "product_analytics"}]
        with patch(
            "ee.partners.stripe.api.provisioning.services_catalog.requests.get",
            return_value=_billing_response(products),
        ):
            fresh = get_services()

        # Expire the cache window, then make billing unavailable: the stale entry is served
        # rather than falling back to the static description.
        cache.set(SERVICES_CACHE_EXPIRES_KEY, 0, 60)
        with patch(
            "ee.partners.stripe.api.provisioning.services_catalog.requests.get",
            side_effect=Exception("billing down"),
        ):
            stale = get_services()

        assert stale == fresh
        analytics = next(s for s in stale if s["id"] == ANALYTICS_SERVICE_ID)
        assert analytics["description"] != _FALLBACK_DESCRIPTION
