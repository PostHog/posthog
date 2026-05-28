from unittest.mock import MagicMock, patch

from posthog.test.base import APIBaseTest

from rest_framework import status

from posthog.api.test.dashboards import DashboardAPI

from parameterized import parameterized

from posthog.rbac.user_access_control import UserAccessControl

from products.dashboards.backend.widgets.config import DEFAULT_FILTER_TEST_ACCOUNTS, MAX_WIDGET_CONFIG_LIMIT
from products.dashboards.backend.widgets.error_tracking_list import (
    ERROR_TRACKING_ORDER_BY,
    validate_error_tracking_list_config,
)
    SESSION_REPLAY_ORDER_BY,
    validate_session_replay_list_config,
)
from products.dashboards.backend.widget_registry import (
    EXPECTED_WIDGET_TYPES,
    get_widget_registry_entry,
    validate_widget_config,
)


class TestWidgetRegistry(APIBaseTest):
    def test_expected_widget_types_matches_registry(self) -> None:
        from products.dashboards.backend.widget_registry import WIDGET_REGISTRY

        assert EXPECTED_WIDGET_TYPES == frozenset(WIDGET_REGISTRY.keys())

    def test_widget_catalog_matches_registry(self) -> None:
        from products.dashboards.backend.widget_catalog import WIDGET_CATALOG

        assert frozenset(WIDGET_CATALOG.keys()) == EXPECTED_WIDGET_TYPES
        for widget_type, entry in WIDGET_CATALOG.items():
            assert entry["widget_type"] == widget_type

    def test_validate_error_tracking_list_config_defaults(self) -> None:
        validated = validate_error_tracking_list_config({})
        assert validated["limit"] == MAX_WIDGET_CONFIG_LIMIT
        assert validated["orderBy"] == "occurrences"
        assert validated["filterTestAccounts"] is DEFAULT_FILTER_TEST_ACCOUNTS

    def test_validate_error_tracking_list_config_rejects_invalid_filter_test_accounts(self) -> None:
        with self.assertRaises(Exception):
            validate_error_tracking_list_config({"filterTestAccounts": "yes"})

    def test_validate_error_tracking_list_config_rejects_high_limit(self) -> None:
        with self.assertRaises(Exception):
            validate_error_tracking_list_config({"limit": 100})

    @parameterized.expand(["-1h", "-3h", "-24h"])
    def test_validate_error_tracking_list_config_accepts_short_date_ranges(self, date_from: str) -> None:
        validated = validate_error_tracking_list_config({"dateRange": {"date_from": date_from}})
        assert validated["dateRange"] == {"date_from": date_from}

    def test_validate_error_tracking_list_config_rejects_unsupported_date_range(self) -> None:
        with self.assertRaises(Exception):
            validate_error_tracking_list_config({"dateRange": {"date_from": "-48h"}})

class TestDashboardRunWidgets(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.dashboard_api = DashboardAPI(self.client, self.team, self.assertEqual)
        self.widgets_flag_patcher = patch(
            "products.dashboards.backend.api.dashboard.dashboard_widgets_enabled",
            return_value=True,
        )
        self.widgets_flag_patcher.start()

    def tearDown(self) -> None:
        self.widgets_flag_patcher.stop()
        super().tearDown()

    def _run(self, dashboard_id: int, tile_ids: list[int]) -> dict:
        response = self.client.get(
            f"/api/projects/{self.team.id}/dashboards/{dashboard_id}/run_widgets/",
            {"tile_ids": ",".join(str(tile_id) for tile_id in tile_ids)},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        return response.json()

    def test_requires_tile_ids(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dash"})
        response = self.client.get(f"/api/projects/{self.team.id}/dashboards/{dashboard_id}/run_widgets/")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch(
        "products.error_tracking.backend.hogql_queries.error_tracking_query_runner.ErrorTrackingQueryRunner.calculate"
    )
    def test_runs_widget_for_requested_tile(self, mock_calculate: MagicMock) -> None:
        mock_calculate.return_value = MagicMock(
            model_dump=lambda mode="json": {"results": [], "hasMore": False, "limit": 10, "offset": 0}
        )
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dash"})
        _, dashboard_json = self.dashboard_api.create_widget_tile(dashboard_id, config={"limit": 10})
        tile_id = dashboard_json["tiles"][0]["id"]

        body = self._run(dashboard_id, [tile_id])

        self.assertEqual(len(body["results"]), 1)
        self.assertEqual(body["results"][0]["tile_id"], tile_id)
        self.assertEqual(body["results"][0]["widget_type"], "error_tracking_list")
        self.assertIsNone(body["results"][0]["error"])
        self.assertEqual(body["results"][0]["result"]["limit"], 10)
        mock_calculate.assert_called_once()

    def test_run_widgets_applies_filter_test_accounts_when_enabled(self, mock_runner_cls: MagicMock) -> None:
        mock_runner_cls.return_value.calculate.return_value = MagicMock(
            model_dump=lambda mode="json": {"results": [], "hasMore": False, "limit": 10, "offset": 0}
        )
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dash"})
        _, dashboard_json = self.dashboard_api.create_widget_tile(
            dashboard_id, config={"limit": 10, "filterTestAccounts": True}
        )
        tile_id = dashboard_json["tiles"][0]["id"]

        self._run(dashboard_id, [tile_id])

        mock_runner_cls.assert_called_once()
        query = mock_runner_cls.call_args.kwargs["query"]
        self.assertTrue(query.filterTestAccounts)

    @patch("products.dashboards.backend.widgets.error_tracking_list.ErrorTrackingQueryRunner")
    def test_run_widgets_skips_filter_test_accounts_when_disabled(self, mock_runner_cls: MagicMock) -> None:
        mock_runner_cls.return_value.calculate.return_value = MagicMock(
            model_dump=lambda mode="json": {"results": [], "hasMore": False, "limit": 10, "offset": 0}
        )
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dash"})
        _, dashboard_json = self.dashboard_api.create_widget_tile(
            dashboard_id, config={"limit": 10, "filterTestAccounts": False}
        )
        tile_id = dashboard_json["tiles"][0]["id"]

        self._run(dashboard_id, [tile_id])

        mock_runner_cls.assert_called_once()
        query = mock_runner_cls.call_args.kwargs["query"]
        self.assertFalse(query.filterTestAccounts)

    def test_rejects_foreign_tile_id(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dash"})
        other_id, _ = self.dashboard_api.create_dashboard({"name": "other"})
        _, dashboard_json = self.dashboard_api.create_widget_tile(dashboard_id)
        tile_id = dashboard_json["tiles"][0]["id"]

        body = self._run(other_id, [tile_id])

        self.assertEqual(body["results"][0]["error"], "Tile not found or is not a widget tile.")

    @patch("products.dashboards.backend.api.dashboard.dashboard_widgets_enabled", return_value=False)
    def test_disabled_when_feature_flag_off(self, _mock_flag: patch) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dash"})
        response = self.client.get(
            f"/api/projects/{self.team.id}/dashboards/{dashboard_id}/run_widgets/",
            {"tile_ids": "1"},
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_validate_widget_config_unknown_type(self) -> None:
        with self.assertRaises(Exception):
            validate_widget_config("not_a_widget", {})

    def test_error_tracking_widget_type_alias(self) -> None:
        self.assertIs(get_widget_registry_entry("error_tracking"), get_widget_registry_entry("error_tracking_list"))
        validated = validate_widget_config("error_tracking", {"limit": 5})
        self.assertEqual(validated["limit"], 5)

    def test_run_widgets_denies_without_product_access(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dash"})
        _, dashboard_json = self.dashboard_api.create_widget_tile(dashboard_id, widget_type="error_tracking_list")
        tile_id = dashboard_json["tiles"][0]["id"]

        real_check = UserAccessControl.check_access_level_for_resource

        def deny_error_tracking_only(
            user_access_control: UserAccessControl, resource: str, required_level: str = "viewer"
        ) -> bool:
            if resource == "error_tracking":
                return False
            return real_check(user_access_control, resource, required_level)

        with patch.object(
            UserAccessControl,
            "check_access_level_for_resource",
            autospec=True,
            side_effect=deny_error_tracking_only,
        ):
            body = self._run(dashboard_id, [tile_id])

        self.assertEqual(len(body["results"]), 1)
        self.assertEqual(body["results"][0]["tile_id"], tile_id)
        self.assertEqual(body["results"][0]["widget_type"], "error_tracking_list")
        self.assertIsNone(body["results"][0]["result"])
        self.assertEqual(body["results"][0]["error"], "You do not have access to error tracking.")
