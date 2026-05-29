from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized
from rest_framework import status

from posthog.api.test.dashboards import DashboardAPI
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value
from posthog.rbac.user_access_control import UserAccessControl

from products.dashboards.backend.widget_layouts import MAX_WIDGETS_BATCH_SIZE
from products.dashboards.backend.widget_registry import (
    EXPECTED_WIDGET_TYPES,
    WIDGET_REGISTRY,
    get_widget_registry_entry,
    validate_widget_config,
)
from products.dashboards.backend.widgets.config import MAX_WIDGET_CONFIG_LIMIT
from products.dashboards.backend.widgets.error_tracking_list import validate_error_tracking_list_config


class TestWidgetRegistry(APIBaseTest):
    def test_widget_registry_catalog_and_expected_types_stay_in_sync(self) -> None:
        from products.dashboards.backend.widget_catalog import WIDGET_CATALOG

        registry_types = frozenset(WIDGET_REGISTRY.keys())
        assert EXPECTED_WIDGET_TYPES == registry_types
        assert frozenset(WIDGET_CATALOG.keys()) == registry_types
        for widget_type, entry in WIDGET_CATALOG.items():
            assert entry["widget_type"] == widget_type

    def test_validate_widget_config_unknown_type(self) -> None:
        with self.assertRaises(Exception):
            validate_widget_config("not_a_widget", {})

    def test_error_tracking_widget_type_alias(self) -> None:
        self.assertIs(get_widget_registry_entry("error_tracking"), get_widget_registry_entry("error_tracking_list"))
        validated = validate_widget_config("error_tracking", {"limit": 5})
        self.assertEqual(validated["limit"], 5)

    def test_validate_error_tracking_list_config_defaults(self) -> None:
        validated = validate_error_tracking_list_config({})
        assert validated["limit"] == MAX_WIDGET_CONFIG_LIMIT
        assert validated["orderBy"] == "occurrences"
        assert "filterTestAccounts" not in validated

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

    def test_validate_error_tracking_list_config_strips_unknown_date_range_keys(self) -> None:
        validated = validate_error_tracking_list_config(
            {"dateRange": {"date_from": "-7d", "date_to": "ignored", "evil": 1}}
        )
        assert validated["dateRange"] == {"date_from": "-7d"}


class TestDashboardRunWidgets(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.dashboard_api = DashboardAPI(self.client, self.team, self.assertEqual)
        self.widgets_flag_patcher = patch(
            "products.dashboards.backend.api.dashboard.dashboard_widgets_enabled",
            return_value=True,
        )
        self.widget_create_flag_patcher = patch(
            "products.dashboards.backend.widget_create.dashboard_widgets_enabled",
            return_value=True,
        )
        self.widgets_flag_patcher.start()
        self.widget_create_flag_patcher.start()

    def tearDown(self) -> None:
        self.widget_create_flag_patcher.stop()
        self.widgets_flag_patcher.stop()
        super().tearDown()

    def _run(self, dashboard_id: int, tile_ids: list[int]) -> dict:
        response = self.client.get(
            f"/api/projects/{self.team.id}/dashboards/{dashboard_id}/run_widgets/",
            {"tile_ids": ",".join(str(tile_id) for tile_id in tile_ids)},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        return response.json()

    @parameterized.expand(
        [
            ("missing_param", None, "tile_ids is required"),
            ("empty_param", "", "tile_ids is required"),
            ("non_integer", "abc", "tile_ids must be a comma-separated list of integers"),
        ]
    )
    def test_run_widgets_rejects_invalid_tile_ids_param(
        self, _name: str, tile_ids_param: str | None, expected_detail: str
    ) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dash"})
        query_params = {} if tile_ids_param is None else {"tile_ids": tile_ids_param}
        response = self.client.get(
            f"/api/projects/{self.team.id}/dashboards/{dashboard_id}/run_widgets/",
            query_params,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn(expected_detail, response.json()["detail"])

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

    @patch("products.dashboards.backend.widgets.error_tracking_list.ErrorTrackingQueryRunner")
    def test_run_widgets_uses_team_filter_test_accounts_default(self, mock_runner_cls: MagicMock) -> None:
        mock_runner_cls.return_value.calculate.return_value = MagicMock(
            model_dump=lambda mode="json": {"results": [], "hasMore": False, "limit": 10, "offset": 0}
        )
        self.team.test_account_filters_default_checked = True
        self.team.save()
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dash"})
        _, dashboard_json = self.dashboard_api.create_widget_tile(dashboard_id, config={"limit": 10})
        tile_id = dashboard_json["tiles"][0]["id"]

        self._run(dashboard_id, [tile_id])

        query = mock_runner_cls.call_args.kwargs["query"]
        self.assertTrue(query.filterTestAccounts)

    @patch("products.dashboards.backend.widgets.error_tracking_list.ErrorTrackingQueryRunner")
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
        self.assertEqual(mock_runner_cls.call_args.kwargs["user"], self.user)
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

    def test_rejects_non_widget_tile(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dash"})
        insight_id, _ = self.dashboard_api.create_insight({"name": "insight"})
        self.dashboard_api.add_insight_to_dashboard([dashboard_id], insight_id)
        dashboard_json = self.dashboard_api.get_dashboard(dashboard_id)
        insight_tile_id = next(tile["id"] for tile in dashboard_json["tiles"] if tile.get("insight"))

        body = self._run(dashboard_id, [insight_tile_id])

        self.assertEqual(body["results"][0]["error"], "Tile not found or is not a widget tile.")

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

    def test_run_widgets_rejects_too_many_tile_ids(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dash"})
        tile_ids = list(range(1, MAX_WIDGETS_BATCH_SIZE + 2))

        response = self.client.get(
            f"/api/projects/{self.team.id}/dashboards/{dashboard_id}/run_widgets/",
            {"tile_ids": ",".join(str(tile_id) for tile_id in tile_ids)},
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn(str(MAX_WIDGETS_BATCH_SIZE), response.json()["detail"])

    @patch(
        "products.error_tracking.backend.hogql_queries.error_tracking_query_runner.ErrorTrackingQueryRunner.calculate"
    )
    def test_run_widgets_deduplicates_tile_ids(self, mock_calculate: MagicMock) -> None:
        mock_calculate.return_value = MagicMock(
            model_dump=lambda mode="json": {"results": [], "hasMore": False, "limit": 10, "offset": 0}
        )
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dash"})
        _, dashboard_json = self.dashboard_api.create_widget_tile(dashboard_id, config={"limit": 10})
        tile_id = dashboard_json["tiles"][0]["id"]

        body = self._run(dashboard_id, [tile_id, tile_id])

        self.assertEqual(len(body["results"]), 1)
        mock_calculate.assert_called_once()

    @patch("products.dashboards.backend.widgets.error_tracking_list.ErrorTrackingQueryRunner")
    def test_run_widgets_hides_query_exception_details(self, mock_runner_cls: MagicMock) -> None:
        mock_runner_cls.return_value.calculate.side_effect = Exception("SELECT * FROM secret_table")
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dash"})
        _, dashboard_json = self.dashboard_api.create_widget_tile(dashboard_id, config={"limit": 10})
        tile_id = dashboard_json["tiles"][0]["id"]

        body = self._run(dashboard_id, [tile_id])

        self.assertEqual(
            body["results"][0]["error"],
            "Widget query failed. Please try again later.",
        )
        self.assertNotIn("secret_table", body["results"][0]["error"])

    def test_run_widgets_denies_without_api_scope_on_personal_api_key(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dash"})
        _, dashboard_json = self.dashboard_api.create_widget_tile(dashboard_id)
        tile_id = dashboard_json["tiles"][0]["id"]

        token = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="dashboard only",
            user=self.user,
            secure_value=hash_key_value(token),
            scopes=["dashboard:read"],
            scoped_teams=[],
            scoped_organizations=[],
        )

        response = self.client.get(
            f"/api/projects/{self.team.id}/dashboards/{dashboard_id}/run_widgets/",
            {"tile_ids": str(tile_id)},
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertEqual(body["results"][0]["error"], "API key missing required scope 'error_tracking:read'")
