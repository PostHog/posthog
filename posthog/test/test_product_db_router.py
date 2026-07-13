import tempfile
from pathlib import Path
from types import SimpleNamespace

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from posthog.product_db_config import ProductDBRoute, load_product_db_routes
from posthog.product_db_router import (
    ProductDBRouter,
    check_product_db_routes,
    get_product_db_routes,
    product_db_routes_configured_errors,
)

FAKE_PRODUCT_DATABASES: dict[str, dict] = {
    "default": {},
    "visual_review_db_writer": {},
    "visual_review_db_reader": {},
}


def _visual_review_route(optional: bool = False) -> ProductDBRoute:
    return ProductDBRoute(
        app_label="visual_review",
        database="visual_review",
        source="products/db_routing.yaml",
        optional=optional,
    )


@override_settings(DATABASES=FAKE_PRODUCT_DATABASES)
class TestProductDBRouter(SimpleTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.router = ProductDBRouter(routes=(_visual_review_route(),))

    def test_routes_visual_review_model_to_configured_aliases(self) -> None:
        model = SimpleNamespace(_meta=SimpleNamespace(app_label="visual_review", model_name="run"))

        # In TEST mode, reads go to the writer so they share the same transaction.
        self.assertEqual(self.router.db_for_read(model), "visual_review_db_writer")
        self.assertEqual(self.router.db_for_write(model), "visual_review_db_writer")

    def test_does_not_route_other_apps(self) -> None:
        model = SimpleNamespace(_meta=SimpleNamespace(app_label="posthog", model_name="person"))

        self.assertIsNone(self.router.db_for_read(model))
        self.assertIsNone(self.router.db_for_write(model))

    @override_settings(DATABASES={"default": {}})
    def test_only_enables_routes_with_configured_aliases(self) -> None:
        router = ProductDBRouter(routes=(_visual_review_route(),))

        model = SimpleNamespace(_meta=SimpleNamespace(app_label="visual_review", model_name="run"))

        self.assertIsNone(router.db_for_read(model))
        self.assertIsNone(router.db_for_write(model))


class TestProductDBRouteLoading(SimpleTestCase):
    def test_loads_visual_review_db_routing_yaml(self) -> None:
        routes = load_product_db_routes(Path(__file__).resolve().parents[2])
        visual_review_routes = [route for route in routes if route.app_label == "visual_review"]

        self.assertEqual(len(visual_review_routes), 1)
        self.assertEqual(visual_review_routes[0].database, "visual_review")
        self.assertTrue(visual_review_routes[0].source.endswith("products/db_routing.yaml"))

    def test_parses_optional_flag(self) -> None:
        with tempfile.TemporaryDirectory() as base_dir:
            config_path = Path(base_dir) / "products" / "db_routing.yaml"
            config_path.parent.mkdir(parents=True)
            config_path.write_text(
                "routes:\n"
                "  - app_label: staged_product\n"
                "    database: staged_product\n"
                "    optional: true\n"
                "  - app_label: established_product\n"
                "    database: established_product\n"
                "  - app_label: quoted_product\n"
                "    database: quoted_product\n"
                '    optional: "false"\n'
            )

            routes = {route.app_label: route for route in load_product_db_routes(base_dir)}

        self.assertTrue(routes["staged_product"].optional)
        self.assertFalse(routes["established_product"].optional)
        # Non-boolean values fail closed: a quoted "false" is a truthy string.
        self.assertFalse(routes["quoted_product"].optional)


class TestProductDBRouteChecks(SimpleTestCase):
    @override_settings(BASE_DIR=Path(__file__).resolve().parents[2])
    def test_check_passes_for_valid_route_config(self) -> None:
        get_product_db_routes.cache_clear()
        self.addCleanup(get_product_db_routes.cache_clear)

        self.assertEqual(check_product_db_routes(None), [])


class TestProductDBRoutesConfiguredCheck(SimpleTestCase):
    @parameterized.expand(
        [
            ("enforced_on_cloud", "US", False, 1),
            ("self_hosted_unenforced", None, False, 0),
            ("e2e_unenforced", "E2E", False, 0),
            ("optional_route_allowed", "US", True, 0),
        ]
    )
    def test_missing_writer_alias(self, _name, cloud_deployment, optional, expected_errors) -> None:
        route = _visual_review_route(optional=optional)
        with override_settings(DATABASES={"default": {}}, CLOUD_DEPLOYMENT=cloud_deployment, TEST=False):
            errors = product_db_routes_configured_errors((route,))

        self.assertEqual(len(errors), expected_errors)
        if expected_errors:
            self.assertEqual(errors[0].id, "posthog.E005")

    def test_configured_route_passes(self) -> None:
        with override_settings(
            DATABASES={"default": {}, "visual_review_db_writer": {}},
            CLOUD_DEPLOYMENT="US",
            TEST=False,
        ):
            self.assertEqual(product_db_routes_configured_errors((_visual_review_route(),)), [])

    def test_configured_optional_route_warns_to_remove_flag(self) -> None:
        with override_settings(
            DATABASES={"default": {}, "visual_review_db_writer": {}},
            CLOUD_DEPLOYMENT="US",
            TEST=False,
        ):
            messages = product_db_routes_configured_errors((_visual_review_route(optional=True),))

        self.assertEqual([message.id for message in messages], ["posthog.W001"])
