from types import ModuleType

from django.test import SimpleTestCase
from django.urls import path, resolve, reverse

from parameterized import parameterized

import posthog.urls
from posthog.api import api_not_found
from posthog.product_urls import ProductRootRoutes, ProductRouteError


def _routes_module(product: str, *routes: str) -> ModuleType:
    module = ModuleType(f"products.{product}.backend.routes")
    module.urlpatterns = [path(route, lambda request: None) for route in routes]  # type: ignore[attr-defined]
    return module


class TestProductRootRoutes(SimpleTestCase):
    def test_collects_the_patterns_a_product_declares(self) -> None:
        module = _routes_module("stamphog", "webhooks/stamphog/github", "api/stamphog/thing")

        collected = ProductRootRoutes.from_module(module)

        assert [str(pattern.pattern) for pattern in collected] == [
            "webhooks/stamphog/github",
            "api/stamphog/thing",
        ]

    def test_a_module_without_urlpatterns_contributes_nothing(self) -> None:
        assert ProductRootRoutes.from_module(ModuleType("products.stamphog.backend.routes")) == []

    @parameterized.expand(
        [
            ("core namespace", "webhooks/github"),
            ("another product", "api/legal_documents/pandadoc"),
            ("prefix without the separator", "webhooks/stamphogus/github"),
            ("unreserved namespace", "internal/stamphog/thing"),
        ]
    )
    def test_rejects_a_route_outside_the_products_own_prefixes(self, _name: str, route: str) -> None:
        module = _routes_module("stamphog", route)

        with self.assertRaises(ProductRouteError) as caught:
            ProductRootRoutes.from_module(module)

        assert str(caught.exception) == (
            f"Product 'stamphog' declares root URL pattern {route!r}, which must start with "
            "'api/stamphog/' or 'webhooks/stamphog/'"
        )


class TestProductRootRouteSlot(SimpleTestCase):
    def test_product_routes_sit_after_core_routes_and_before_the_api_fallback(self) -> None:
        names = [getattr(pattern, "name", None) for pattern in posthog.urls.urlpatterns]
        routes = [str(pattern.pattern) for pattern in posthog.urls.urlpatterns]

        assert names.index("schema") < names.index("user_interviews_vapi_webhook")
        assert names.index("user_interviews_vapi_webhook") < routes.index("^api.+")

    def test_the_api_fallback_does_not_shadow_a_moved_product_route(self) -> None:
        assert reverse("user_interviews_vapi_webhook") == "/api/user_interviews/vapi_webhook/"
        assert resolve("/api/user_interviews/vapi_webhook/").func is not api_not_found
