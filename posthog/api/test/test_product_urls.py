from types import ModuleType

from django.http import HttpRequest, HttpResponse
from django.test import SimpleTestCase
from django.urls import path, re_path, resolve, reverse

from parameterized import parameterized

import posthog.urls
from posthog.api import api_not_found
from posthog.product_urls import ProductRootRoutes, ProductRouteError
from posthog.utils import opt_slash_path


def _view(request: HttpRequest) -> HttpResponse:
    return HttpResponse()


def _routes_module(product: str, *routes: str) -> ModuleType:
    module = ModuleType(f"products.{product}.backend.routes")
    module.urlpatterns = [path(route, _view) for route in routes]  # type: ignore[attr-defined]
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

    @parameterized.expand(
        [
            ("bare regex", "webhooks/stamphog/github"),
            ("regex ending in a group", "webhooks/stamphog/github/?"),
        ]
    )
    def test_rejects_an_unanchored_regex_route(self, _name: str, regex: str) -> None:
        module = ModuleType("products.stamphog.backend.routes")
        module.urlpatterns = [re_path(regex, _view)]  # type: ignore[attr-defined]

        with self.assertRaises(ProductRouteError) as caught:
            ProductRootRoutes.from_module(module)

        assert str(caught.exception) == (
            f"Product 'stamphog' declares root URL pattern {regex!r} as an unanchored regex, "
            "which matches anywhere in the path. Start it with '^'"
        )

    def test_accepts_the_anchored_regex_opt_slash_path_builds(self) -> None:
        module = ModuleType("products.stamphog.backend.routes")
        module.urlpatterns = [opt_slash_path("webhooks/stamphog/github", _view)]  # type: ignore[attr-defined]

        assert len(ProductRootRoutes.from_module(module)) == 1


class TestProductRootRouteSlot(SimpleTestCase):
    def test_product_routes_sit_after_core_routes_and_before_the_api_fallback(self) -> None:
        names = [getattr(pattern, "name", None) for pattern in posthog.urls.urlpatterns]
        routes = [str(pattern.pattern) for pattern in posthog.urls.urlpatterns]

        assert names.index("schema") < names.index("user_interviews_vapi_webhook")
        assert names.index("user_interviews_vapi_webhook") < routes.index("^api.+")

    def test_the_api_fallback_does_not_shadow_a_moved_product_route(self) -> None:
        assert reverse("user_interviews_vapi_webhook") == "/api/user_interviews/vapi_webhook/"
        assert resolve("/api/user_interviews/vapi_webhook/").func is not api_not_found
