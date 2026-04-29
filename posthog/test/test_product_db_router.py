from pathlib import Path
from types import SimpleNamespace

from django.test import SimpleTestCase, override_settings

from posthog.product_db_config import ProductDBRoute, load_product_db_routes
from posthog.product_db_router import ProductDBRouter, check_product_db_routes, get_product_db_routes

FAKE_PRODUCT_DATABASES: dict[str, dict] = {
    "default": {},
    "visual_review_db_writer": {},
    "visual_review_db_reader": {},
}


@override_settings(DATABASES=FAKE_PRODUCT_DATABASES)
class TestProductDBRouter(SimpleTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.router = ProductDBRouter(
            routes=(
                ProductDBRoute(
                    app_label="visual_review",
                    database="visual_review",
                    source="products/db_routing.yaml",
                ),
            )
        )

    def test_routes_visual_review_model_to_configured_aliases(self) -> None:
        model = SimpleNamespace(_meta=SimpleNamespace(app_label="visual_review", model_name="run"))

        # In TEST mode, reads go to the writer so they share the same transaction.
        assert self.router.db_for_read(model) == "visual_review_db_writer"
        assert self.router.db_for_write(model) == "visual_review_db_writer"

    def test_does_not_route_other_apps(self) -> None:
        model = SimpleNamespace(_meta=SimpleNamespace(app_label="posthog", model_name="person"))

        assert self.router.db_for_read(model) is None
        assert self.router.db_for_write(model) is None

    @override_settings(DATABASES={"default": {}})
    def test_only_enables_routes_with_configured_aliases(self) -> None:
        router = ProductDBRouter(
            routes=(
                ProductDBRoute(
                    app_label="visual_review",
                    database="visual_review",
                    source="products/db_routing.yaml",
                ),
            )
        )

        model = SimpleNamespace(_meta=SimpleNamespace(app_label="visual_review", model_name="run"))

        assert router.db_for_read(model) is None
        assert router.db_for_write(model) is None


class TestProductDBRouteLoading(SimpleTestCase):
    def test_loads_visual_review_db_routing_yaml(self) -> None:
        routes = load_product_db_routes(Path(__file__).resolve().parents[2])
        visual_review_routes = [route for route in routes if route.app_label == "visual_review"]

        assert len(visual_review_routes) == 1
        assert visual_review_routes[0].database == "visual_review"
        assert visual_review_routes[0].source.endswith("products/db_routing.yaml")


class TestProductDBRouteChecks(SimpleTestCase):
    @override_settings(BASE_DIR=Path(__file__).resolve().parents[2])
    def test_check_passes_for_valid_route_config(self) -> None:
        get_product_db_routes.cache_clear()
        self.addCleanup(get_product_db_routes.cache_clear)

        assert check_product_db_routes(None) == []
