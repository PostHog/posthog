from types import ModuleType

from django.core.exceptions import ImproperlyConfigured
from django.http import HttpRequest, HttpResponse
from django.test import SimpleTestCase
from django.urls import path, resolve, reverse

from parameterized import parameterized

from posthog.product_urls import ProductRootRoutes
from posthog.utils import opt_slash_path


def _view(request: HttpRequest) -> HttpResponse:
    return HttpResponse()


def _routes_module() -> ModuleType:
    return ModuleType("products.stamphog.backend.routes")


class TestProductRootRoutes(SimpleTestCase):
    def test_mounts_each_declared_list_under_the_prefix_reserved_for_the_product(self) -> None:
        module = _routes_module()
        module.api_urlpatterns = [path("thing", _view)]  # type: ignore[attr-defined]
        module.webhook_urlpatterns = [opt_slash_path("github", _view)]  # type: ignore[attr-defined]

        mounts = ProductRootRoutes.from_module(module)

        assert [str(mount.pattern) for mount in mounts] == ["api/stamphog/", "webhooks/stamphog/"]

    def test_a_module_that_declares_no_list_contributes_nothing(self) -> None:
        assert ProductRootRoutes.from_module(_routes_module()) == []

    @parameterized.expand([("urlpatterns",), ("webhooks_urlpatterns",), ("api_url_patterns",)])
    def test_a_module_that_declares_an_unmounted_list_fails_the_url_conf(self, name: str) -> None:
        module = _routes_module()
        setattr(module, name, [path("thing", _view)])

        with self.assertRaises(ImproperlyConfigured) as caught:
            ProductRootRoutes.from_module(module)

        assert name in str(caught.exception)
        assert "'api_urlpatterns'" in str(caught.exception)


class TestProductRootRoutesInTheUrlConf(SimpleTestCase):
    @parameterized.expand(
        [
            ("a path a product declares", "/api/user_interviews/vapi_webhook/", "user_interviews_vapi_webhook"),
            ("a path without a trailing slash", "/api/legal_documents/pandadoc", "legal_document_pandadoc_webhook"),
            ("a list a product includes", "/api/customer_analytics/external/account", "external-account"),
        ]
    )
    def test_a_mounted_route_keeps_its_url_and_its_global_name(self, _name: str, url: str, route_name: str) -> None:
        assert resolve(url).url_name == route_name
        assert reverse(route_name) == url

    @parameterized.expand(
        [
            ("stamphog bare", "/webhooks/stamphog/github", "github_stamphog_webhook"),
            ("stamphog trailing slash", "/webhooks/stamphog/github/", "github_stamphog_webhook"),
            ("workflows bare", "/webhooks/workflows/ses-events", "sns_default_webhook"),
            ("workflows trailing slash", "/webhooks/workflows/ses-events/", "sns_default_webhook"),
        ]
    )
    def test_an_opt_slash_route_matches_relative_to_its_mount(self, _name: str, url: str, view_name: str) -> None:
        assert resolve(url).func.__name__ == view_name
