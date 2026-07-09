import typing
from typing import Any, cast

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.test.utils import override_settings

from parameterized import parameterized
from rest_framework import status

from posthog.schema import RecordingOrder, RecordingOrderDirection

from posthog.api.test.dashboards import DashboardAPI
from posthog.clickhouse.client.execute import UntaggedQueryError
from posthog.clickhouse.query_tagging import Feature, Product, get_query_tags
from posthog.models import Team
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value
from posthog.rbac.user_access_control import AccessControlLevel, UserAccessControl
from posthog.scopes import APIScopeObject
from posthog.session_recordings.models.session_recording import SessionRecording
from posthog.session_recordings.models.session_recording_playlist import SessionRecordingPlaylist
from posthog.session_recordings.models.session_recording_playlist_item import SessionRecordingPlaylistItem
from posthog.slo.types import SloOperation, SloOutcome
from posthog.test.persons import create_person

from products.dashboards.backend.api import widget_openapi_serializers as widget_openapi_serializers_module
from products.dashboards.backend.constants import (
    ACTIVITY_EVENTS_DEFAULT_LIMIT,
    ACTIVITY_EVENTS_MAX_LIMIT,
    DEFAULT_WIDGET_LIST_LIMIT,
    LOGS_LIST_DEFAULT_LIMIT,
    LOGS_LIST_MAX_LIMIT,
    MAX_WIDGET_RESULT_LIMIT,
    MAX_WIDGETS_BATCH_SIZE,
)
from products.dashboards.backend.widget_catalog import WIDGET_CATALOG
from products.dashboards.backend.widget_registry import EXPECTED_WIDGET_TYPES, WIDGET_REGISTRY, validate_widget_config
from products.dashboards.backend.widget_specs.configs import (
    ACTIVITY_EVENTS_LIST_WIDGET_TYPE,
    ERROR_TRACKING_LIST_WIDGET_TYPE,
    LOGS_LIST_WIDGET_TYPE,
    SESSION_REPLAY_LIST_WIDGET_TYPE,
    ErrorTrackingListWidgetConfig,
    SessionReplayOrderBy,
)
from products.dashboards.backend.widget_specs.pydantic_openapi import pydantic_model_to_openapi_components
from products.dashboards.backend.widgets.activity_events_list import (
    ACTIVITY_EVENTS_WIDGET_SELECT,
    run_activity_events_list_widget,
)
from products.dashboards.backend.widgets.error_tracking_list import run_error_tracking_list_widget
from products.dashboards.backend.widgets.logs_list import run_logs_list_widget
from products.dashboards.backend.widgets.session_replay_list import run_session_replay_list_widget
from products.error_tracking.backend.facade.query_utils import ERROR_TRACKING_LISTING_VOLUME_RESOLUTION
from products.logs.backend.models import LogsView


class TestWidgetRegistry(APIBaseTest):
    def test_widget_registry_catalog_and_expected_types_stay_in_sync(self) -> None:
        registry_types = frozenset(WIDGET_REGISTRY.keys())
        assert EXPECTED_WIDGET_TYPES == registry_types
        assert frozenset(WIDGET_CATALOG.keys()) == registry_types
        for widget_type, entry in WIDGET_CATALOG.items():
            assert entry["widget_type"] == widget_type

    def test_openapi_widget_config_serializers_match_registry(self) -> None:
        openapi_serializers = widget_openapi_serializers_module.DashboardWidgetConfigOpenApi.serializers
        assert len(openapi_serializers) == len(EXPECTED_WIDGET_TYPES), (
            "Each WIDGET_SPECS entry must produce a config serializer in widget_specs/openapi.py. "
            f"serializers={len(openapi_serializers)} expected={len(EXPECTED_WIDGET_TYPES)}"
        )

    def test_widget_config_openapi_components_include_widget_filters(self) -> None:
        components = pydantic_model_to_openapi_components(ErrorTrackingListWidgetConfig)
        widget_filter_entry = components["WidgetFilterEntry"]
        assert "filterId" in widget_filter_entry["properties"]
        assert "propertyName" in widget_filter_entry["properties"]
        widget_filters = components["ErrorTrackingListWidgetConfig"]["properties"]["widgetFilters"]
        assert "WidgetFilterEntry" in str(widget_filters)

    def test_validate_widget_config_unknown_type(self) -> None:
        with self.assertRaises(Exception):
            validate_widget_config("not_a_widget", {})

    @parameterized.expand(
        [
            ("error_tracking", ERROR_TRACKING_LIST_WIDGET_TYPE, "occurrences"),
            ("session_replay", SESSION_REPLAY_LIST_WIDGET_TYPE, "start_time"),
        ]
    )
    def test_validate_list_config_defaults(self, _label: str, widget_type: str, default_order_by: str) -> None:
        validated = validate_widget_config(widget_type, {})
        assert validated["limit"] == DEFAULT_WIDGET_LIST_LIMIT
        assert validated["orderBy"] == default_order_by
        assert "filterTestAccounts" not in validated

    def test_validate_logs_list_config_defaults(self) -> None:
        # Logs has its own larger page than other list widgets.
        validated = validate_widget_config(LOGS_LIST_WIDGET_TYPE, {})
        assert validated["limit"] == LOGS_LIST_DEFAULT_LIMIT
        assert validated["orderBy"] == "latest"
        assert validated["wrapLines"] is False
        assert validated["timezone"] == "UTC"
        assert "savedViewId" not in validated
        assert "filterTestAccounts" not in validated

    @parameterized.expand(
        [
            ("invalid_order_by", {"orderBy": "not_a_field"}),
            ("invalid_severity_level", {"severityLevels": ["not_a_level"]}),
            ("invalid_timezone", {"timezone": "America/New_York"}),
            ("invalid_saved_view_id", {"savedViewId": 123}),
        ]
    )
    def test_validate_logs_list_config_rejects_invalid_values(self, _label: str, config: dict) -> None:
        with self.assertRaises(Exception):
            validate_widget_config(LOGS_LIST_WIDGET_TYPE, config)

    def test_validate_logs_list_config_accepts_severity_and_services(self) -> None:
        validated = validate_widget_config(
            LOGS_LIST_WIDGET_TYPE,
            {"severityLevels": ["error", "warn"], "serviceNames": ["api", "web"], "orderBy": "earliest"},
        )
        assert validated["severityLevels"] == ["error", "warn"]
        assert validated["serviceNames"] == ["api", "web"]
        assert validated["orderBy"] == "earliest"

    def test_validate_logs_list_config_rejects_test_account_filter(self) -> None:
        # Logs queries have no test-account concept, so the field must not be accepted.
        with self.assertRaises(Exception):
            validate_widget_config(LOGS_LIST_WIDGET_TYPE, cast(dict[str, object], {"filterTestAccounts": True}))

    def test_validate_activity_events_list_config_defaults(self) -> None:
        validated = validate_widget_config(ACTIVITY_EVENTS_LIST_WIDGET_TYPE, {})
        assert validated["limit"] == ACTIVITY_EVENTS_DEFAULT_LIMIT
        assert "orderBy" not in validated
        assert "filterTestAccounts" not in validated

    def test_validate_activity_events_list_config_accepts_limit_up_to_max(self) -> None:
        validated = validate_widget_config(ACTIVITY_EVENTS_LIST_WIDGET_TYPE, {"limit": ACTIVITY_EVENTS_MAX_LIMIT})
        assert validated["limit"] == ACTIVITY_EVENTS_MAX_LIMIT

    def test_validate_activity_events_list_config_rejects_limit_above_max(self) -> None:
        with self.assertRaises(Exception):
            validate_widget_config(ACTIVITY_EVENTS_LIST_WIDGET_TYPE, {"limit": ACTIVITY_EVENTS_MAX_LIMIT + 1})

    @parameterized.expand(
        [
            ("activity_events", ACTIVITY_EVENTS_LIST_WIDGET_TYPE),
            ("error_tracking", ERROR_TRACKING_LIST_WIDGET_TYPE),
            ("session_replay", SESSION_REPLAY_LIST_WIDGET_TYPE),
        ]
    )
    def test_validate_list_config_rejects_invalid_filter_test_accounts(self, _label: str, widget_type: str) -> None:
        with self.assertRaises(Exception):
            validate_widget_config(
                widget_type,
                cast(dict[str, object], {"filterTestAccounts": "yes"}),
            )

    @parameterized.expand(
        [
            ("activity_events", ACTIVITY_EVENTS_LIST_WIDGET_TYPE),
            ("error_tracking", ERROR_TRACKING_LIST_WIDGET_TYPE),
            ("session_replay", SESSION_REPLAY_LIST_WIDGET_TYPE),
        ]
    )
    def test_validate_list_config_rejects_high_limit(self, _label: str, widget_type: str) -> None:
        with self.assertRaises(Exception):
            validate_widget_config(widget_type, {"limit": 100})

    def test_validate_logs_list_config_accepts_limit_up_to_max(self) -> None:
        validated = validate_widget_config(LOGS_LIST_WIDGET_TYPE, {"limit": LOGS_LIST_MAX_LIMIT})
        assert validated["limit"] == LOGS_LIST_MAX_LIMIT

    def test_validate_logs_list_config_rejects_limit_above_max(self) -> None:
        with self.assertRaises(Exception):
            validate_widget_config(LOGS_LIST_WIDGET_TYPE, {"limit": LOGS_LIST_MAX_LIMIT + 1})

    def test_validate_logs_list_config_accepts_display_and_saved_view(self) -> None:
        validated = validate_widget_config(
            LOGS_LIST_WIDGET_TYPE,
            {"wrapLines": True, "timezone": "local", "savedViewId": "abc123"},
        )
        assert validated["wrapLines"] is True
        assert validated["timezone"] == "local"
        assert validated["savedViewId"] == "abc123"

    @parameterized.expand(
        [("activity_events", ACTIVITY_EVENTS_LIST_WIDGET_TYPE, date_from) for date_from in ["-1h", "-3h", "-24h"]]
        + [("error_tracking", ERROR_TRACKING_LIST_WIDGET_TYPE, date_from) for date_from in ["-1h", "-3h", "-24h"]]
        + [("session_replay", SESSION_REPLAY_LIST_WIDGET_TYPE, date_from) for date_from in ["-1h", "-3h", "-24h"]]
        + [("logs", LOGS_LIST_WIDGET_TYPE, date_from) for date_from in ["-1h", "-3h", "-24h"]]
    )
    def test_validate_list_config_accepts_short_date_ranges(
        self, _label: str, widget_type: str, date_from: str
    ) -> None:
        validated = validate_widget_config(
            widget_type,
            {"dateRange": {"date_from": date_from}},
        )
        assert validated["dateRange"] == {"date_from": date_from}

    @parameterized.expand(
        [
            ("activity_events", ACTIVITY_EVENTS_LIST_WIDGET_TYPE),
            ("error_tracking", ERROR_TRACKING_LIST_WIDGET_TYPE),
            ("session_replay", SESSION_REPLAY_LIST_WIDGET_TYPE),
            ("logs", LOGS_LIST_WIDGET_TYPE),
        ]
    )
    def test_validate_list_config_rejects_unsupported_date_range(self, _label: str, widget_type: str) -> None:
        with self.assertRaises(Exception):
            validate_widget_config(
                widget_type,
                {"dateRange": {"date_from": "-48h"}},
            )

    @parameterized.expand(
        [
            ("activity_events", ACTIVITY_EVENTS_LIST_WIDGET_TYPE),
            ("error_tracking", ERROR_TRACKING_LIST_WIDGET_TYPE),
            ("session_replay", SESSION_REPLAY_LIST_WIDGET_TYPE),
            ("logs", LOGS_LIST_WIDGET_TYPE),
        ]
    )
    def test_validate_list_config_strips_unknown_date_range_keys(self, _label: str, widget_type: str) -> None:
        validated = validate_widget_config(
            widget_type,
            {"dateRange": {"date_from": "-7d", "date_to": "ignored", "evil": 1}},
        )
        assert validated["dateRange"] == {"date_from": "-7d"}

    @parameterized.expand(
        [
            ("activity_events", ACTIVITY_EVENTS_LIST_WIDGET_TYPE, "$current_url"),
            ("error_tracking", ERROR_TRACKING_LIST_WIDGET_TYPE, "$environment"),
            ("session_replay", SESSION_REPLAY_LIST_WIDGET_TYPE, "$browser"),
        ]
    )
    def test_validate_list_config_accepts_widget_filters(
        self,
        _label: str,
        widget_type: str,
        property_name: str,
    ) -> None:
        validated = validate_widget_config(
            widget_type,
            {
                "widgetFilters": {
                    "qf-1": {
                        "filterId": "qf-1",
                        "propertyName": property_name,
                        "optionId": "opt-1",
                        "operator": "exact",
                        "value": "production",
                    }
                }
            },
        )
        assert validated["widgetFilters"]["qf-1"]["propertyName"] == property_name

    def test_validate_session_replay_list_config_rejects_invalid_order_by(self) -> None:
        with self.assertRaises(Exception):
            validate_widget_config(SESSION_REPLAY_LIST_WIDGET_TYPE, {"orderBy": "not_a_field"})

    @parameterized.expand(sorted(typing.get_args(SessionReplayOrderBy)))
    def test_validate_session_replay_list_config_accepts_order_by(self, order_by: str) -> None:
        validated = validate_widget_config(
            SESSION_REPLAY_LIST_WIDGET_TYPE,
            {"orderBy": order_by},
        )
        assert validated["orderBy"] == order_by

    @parameterized.expand(["savedFilterId", "collectionId"])
    def test_validate_session_replay_list_config_normalizes_empty_source_id(self, field: str) -> None:
        # The shared short_id validator coerces empty strings to None so they drop out of the config.
        validated = validate_widget_config(SESSION_REPLAY_LIST_WIDGET_TYPE, {field: ""})
        assert field not in validated

        validated = validate_widget_config(SESSION_REPLAY_LIST_WIDGET_TYPE, {field: "abc123"})
        assert validated[field] == "abc123"


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

    @patch("products.error_tracking.backend.facade.queries.ErrorTrackingQueryRunner.calculate")
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

    @patch("posthog.session_recordings.session_recording_api.list_recordings_from_query")
    def test_runs_session_replay_widget_for_requested_tile(self, mock_list_recordings: MagicMock) -> None:
        mock_list_recordings.return_value = ([], False, None, None)
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dash"})
        _, dashboard_json = self.dashboard_api.create_widget_tile(
            dashboard_id, widget_type="session_replay_list", config={"limit": 10}
        )
        tile_id = dashboard_json["tiles"][0]["id"]

        body = self._run(dashboard_id, [tile_id])

        self.assertEqual(len(body["results"]), 1)
        self.assertEqual(body["results"][0]["tile_id"], tile_id)
        self.assertEqual(body["results"][0]["widget_type"], "session_replay_list")
        self.assertIsNone(body["results"][0]["error"])
        self.assertEqual(body["results"][0]["result"]["limit"], 10)
        mock_list_recordings.assert_called_once()
        self.assertEqual(mock_list_recordings.call_args.kwargs["user"], self.user)

    @patch("products.dashboards.backend.widgets.activity_events_list.EventsQueryRunner")
    def test_runs_activity_events_widget_for_requested_tile(self, mock_runner_cls: MagicMock) -> None:
        row = [
            "0196e9ab-0000-0000-0000-000000000000",
            "$pageview",
            {"display_name": "Alex Chen", "id": "1", "distinct_id": "user-1"},
            "https://app.example.test/dashboard",
            "web",
            "2026-05-26T08:00:00Z",
        ]
        mock_runner_cls.return_value.calculate.return_value = MagicMock(
            model_dump=lambda mode="json": {"results": [row], "hasMore": False}
        )
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dash"})
        _, dashboard_json = self.dashboard_api.create_widget_tile(
            dashboard_id, widget_type="activity_events_list", config={"limit": 10}
        )
        tile_id = dashboard_json["tiles"][0]["id"]

        body = self._run(dashboard_id, [tile_id])

        self.assertEqual(len(body["results"]), 1)
        self.assertEqual(body["results"][0]["tile_id"], tile_id)
        self.assertEqual(body["results"][0]["widget_type"], ACTIVITY_EVENTS_LIST_WIDGET_TYPE)
        self.assertIsNone(body["results"][0]["error"])
        result = body["results"][0]["result"]
        self.assertEqual(result["limit"], 10)
        self.assertEqual(
            result["results"][0],
            {
                "uuid": row[0],
                "event": "$pageview",
                "person": {"display_name": "Alex Chen", "id": "1", "distinct_id": "user-1"},
                "url": "https://app.example.test/dashboard",
                "lib": "web",
                "timestamp": "2026-05-26T08:00:00Z",
            },
        )
        self.assertEqual(result["totalCount"], 1)
        self.assertFalse(result["totalCountCapped"])
        mock_runner_cls.assert_called_once()
        self.assertEqual(mock_runner_cls.call_args.kwargs["user"], self.user)
        query = mock_runner_cls.call_args.kwargs["query"]
        self.assertEqual(query.select, ACTIVITY_EVENTS_WIDGET_SELECT)
        self.assertEqual(query.orderBy, ["timestamp DESC"])
        self.assertEqual(query.after, "-24h")

    @patch("products.dashboards.backend.widgets.logs_list.LogsQueryRunner")
    def test_runs_logs_widget_for_requested_tile(self, mock_runner_cls: MagicMock) -> None:
        log_row = {
            "uuid": "0196e9ab-0000-0000-0000-000000000000",
            "timestamp": "2026-05-26T08:00:00Z",
            "severity_text": "error",
            "level": "error",
            "body": "Boom",
            "trace_id": "abc123",
        }
        mock_runner_cls.return_value.calculate.return_value = MagicMock(
            model_dump=lambda mode="json": {"results": [log_row], "hasMore": False}
        )
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dash"})
        _, dashboard_json = self.dashboard_api.create_widget_tile(
            dashboard_id,
            widget_type="logs_list",
            config={
                "limit": 10,
                "severityLevels": ["error"],
                "serviceNames": ["api"],
                "orderBy": "earliest",
            },
        )
        tile_id = dashboard_json["tiles"][0]["id"]

        body = self._run(dashboard_id, [tile_id])

        self.assertEqual(len(body["results"]), 1)
        self.assertEqual(body["results"][0]["tile_id"], tile_id)
        self.assertEqual(body["results"][0]["widget_type"], LOGS_LIST_WIDGET_TYPE)
        self.assertIsNone(body["results"][0]["error"])
        result = body["results"][0]["result"]
        self.assertEqual(result["limit"], 10)
        self.assertEqual(result["results"][0], log_row)
        self.assertEqual(result["totalCount"], 1)
        self.assertFalse(result["totalCountCapped"])
        mock_runner_cls.assert_called_once()
        query = mock_runner_cls.call_args.kwargs["query"]
        self.assertEqual(query.orderBy, "earliest")
        self.assertEqual(query.severityLevels, ["error"])
        self.assertEqual(query.serviceNames, ["api"])
        self.assertTrue(query.excludeAttributes)
        self.assertEqual(query.limit, 10)

    @patch("products.dashboards.backend.widgets.logs_list.LogsQueryRunner")
    def test_runs_logs_widget_with_saved_view(self, mock_runner_cls: MagicMock) -> None:
        mock_runner_cls.return_value.calculate.return_value = MagicMock(
            model_dump=lambda mode="json": {"results": [], "hasMore": False}
        )
        view = LogsView.objects.create(
            team=self.team,
            name="My view",
            filters={
                "severityLevels": ["warn"],
                "serviceNames": ["worker"],
                "searchTerm": "timeout",
                "dateRange": {"date_from": "-3h", "date_to": None},
            },
        )
        # Run the widget in-process: the run_widgets endpoint dispatches to a thread pool whose
        # DB connection can't see the LogsView created in this test's (uncommitted) transaction.
        run_logs_list_widget(
            self.team,
            {
                "limit": 20,
                "orderBy": "earliest",
                "savedViewId": view.short_id,
                # These are ignored once a saved view is selected — the view owns them.
                "severityLevels": ["error"],
                "serviceNames": ["api"],
            },
            user=self.user,
        )

        query = mock_runner_cls.call_args.kwargs["query"]
        self.assertEqual(query.severityLevels, ["warn"])
        self.assertEqual(query.serviceNames, ["worker"])
        self.assertEqual(query.searchTerm, "timeout")
        # Widget still owns sort + page size.
        self.assertEqual(query.orderBy, "earliest")
        self.assertEqual(query.limit, 20)

    @patch("products.dashboards.backend.widgets.logs_list.LogsQueryRunner")
    def test_runs_logs_widget_falls_back_when_saved_view_missing(self, mock_runner_cls: MagicMock) -> None:
        mock_runner_cls.return_value.calculate.return_value = MagicMock(
            model_dump=lambda mode="json": {"results": [], "hasMore": False}
        )
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dash"})
        _, dashboard_json = self.dashboard_api.create_widget_tile(
            dashboard_id,
            widget_type="logs_list",
            config={"limit": 15, "orderBy": "latest", "savedViewId": "missing", "severityLevels": ["error"]},
        )
        tile_id = dashboard_json["tiles"][0]["id"]

        self._run(dashboard_id, [tile_id])

        # Unknown view falls back to the widget's own config rather than erroring.
        query = mock_runner_cls.call_args.kwargs["query"]
        self.assertEqual(query.severityLevels, ["error"])
        self.assertEqual(query.limit, 15)

    @patch("products.dashboards.backend.widgets.logs_list.LogsQueryRunner")
    def test_runs_logs_widget_falls_back_when_saved_view_filters_invalid(self, mock_runner_cls: MagicMock) -> None:
        mock_runner_cls.return_value.calculate.return_value = MagicMock(
            model_dump=lambda mode="json": {"results": [], "hasMore": False}
        )
        # `filters` has no inner schema validation on write, so a stored level outside the enum is possible.
        view = LogsView.objects.create(team=self.team, name="Bad view", filters={"severityLevels": ["critical"]})

        # In-process so the lookup sees the view (see test_runs_logs_widget_with_saved_view). A malformed
        # view degrades to the widget's own config rather than raising.
        run_logs_list_widget(
            self.team,
            {"limit": 12, "orderBy": "latest", "savedViewId": view.short_id, "severityLevels": ["warn"]},
            user=self.user,
        )

        query = mock_runner_cls.call_args.kwargs["query"]
        self.assertEqual(query.severityLevels, ["warn"])
        self.assertEqual(query.limit, 12)

    @patch("products.dashboards.backend.widgets.activity_events_list.EventsQueryRunner")
    def test_activity_events_widget_applies_date_range_and_widget_filters(self, mock_runner_cls: MagicMock) -> None:
        mock_runner_cls.return_value.calculate.return_value = MagicMock(
            model_dump=lambda mode="json": {"results": [], "hasMore": False}
        )

        run_activity_events_list_widget(
            self.team,
            {
                "limit": 5,
                "dateRange": {"date_from": "-7d"},
                "widgetFilters": {
                    "filter-1": {
                        "filterId": "filter-1",
                        "propertyName": "$current_url",
                        "optionId": "opt-1",
                        "operator": "icontains",
                        "value": "/checkout",
                    }
                },
            },
            user=self.user,
        )

        query = mock_runner_cls.call_args.kwargs["query"]
        self.assertEqual(query.after, "-7d")
        assert query.properties is not None
        self.assertEqual(len(query.properties), 1)
        self.assertEqual(query.properties[0].key, "$current_url")
        self.assertEqual(query.properties[0].value, ["/checkout"])

    @parameterized.expand(
        [
            ("with_event", {"limit": 5, "eventName": "$pageview"}, "$pageview"),
            ("without_event", {"limit": 5}, None),
        ]
    )
    @patch("products.dashboards.backend.widgets.activity_events_list.EventsQueryRunner")
    def test_activity_events_widget_event_name_filter(
        self, _label: str, config: dict[str, Any], expected_event: str | None, mock_runner_cls: MagicMock
    ) -> None:
        mock_runner_cls.return_value.calculate.return_value = MagicMock(
            model_dump=lambda mode="json": {"results": [], "hasMore": False}
        )

        run_activity_events_list_widget(self.team, config, user=self.user)

        self.assertEqual(mock_runner_cls.call_args.kwargs["query"].event, expected_event)

    @patch("products.dashboards.backend.widgets.activity_events_list.EventsQueryRunner")
    def test_activity_events_widget_returns_total_count_when_page_has_more(self, mock_runner_cls: MagicMock) -> None:
        def make_row(index: int) -> list[Any]:
            return [f"uuid-{index}", "$pageview", None, None, None, "2026-05-26T08:00:00Z"]

        def calculate_side_effect() -> MagicMock:
            query = mock_runner_cls.call_args.kwargs["query"]
            if query.limit == 1:
                return MagicMock(model_dump=lambda mode="json": {"results": [make_row(0)], "hasMore": True})
            return MagicMock(
                model_dump=lambda mode="json": {"results": [make_row(index) for index in range(3)], "hasMore": False}
            )

        mock_runner_cls.return_value.calculate.side_effect = calculate_side_effect

        result = run_activity_events_list_widget(self.team, {"limit": 1}, user=self.user, include_total_count=True)

        self.assertTrue(result["hasMore"])
        self.assertEqual(result["totalCount"], 3)
        self.assertFalse(result["totalCountCapped"])
        self.assertEqual(len(result["results"]), 1)
        self.assertEqual(mock_runner_cls.call_count, 2)
        count_query = mock_runner_cls.call_args_list[1].kwargs["query"]
        self.assertEqual(count_query.limit, ACTIVITY_EVENTS_MAX_LIMIT)

    @patch(
        "posthog.session_recordings.session_recording_api.ListingSustainedRateThrottle.allow_request", return_value=True
    )
    @patch(
        "posthog.session_recordings.session_recording_api.ListingBurstRateThrottle.allow_request", return_value=False
    )
    @patch("posthog.session_recordings.session_recording_api.ListingBurstRateThrottle.wait", return_value=30)
    @patch("posthog.session_recordings.session_recording_api.list_recordings_from_query")
    def test_run_widgets_applies_replay_listing_throttles(
        self,
        mock_list_recordings: MagicMock,
        _mock_wait: MagicMock,
        _mock_burst_allow: MagicMock,
        _mock_sustained_allow: MagicMock,
    ) -> None:
        mock_list_recordings.return_value = ([], False, None, None)
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dash"})
        _, dashboard_json = self.dashboard_api.create_widget_tile(
            dashboard_id, widget_type="session_replay_list", config={"limit": 10}
        )
        tile_id = dashboard_json["tiles"][0]["id"]

        body = self._run(dashboard_id, [tile_id])

        self.assertEqual(body["results"][0]["error"], "Rate limit exceeded. Expected available in 30 seconds.")
        mock_list_recordings.assert_not_called()

    @patch("posthog.session_recordings.session_recording_api.list_recordings_from_query")
    def test_session_replay_widget_tags_queries_in_debug_mode(self, mock_list_recordings: MagicMock) -> None:
        mock_list_recordings.return_value = ([], False, None, None)

        def assert_tagged(*_args: object, **_kwargs: object) -> tuple[list[object], bool, None, None]:
            tags = get_query_tags()
            if tags.product != Product.REPLAY or tags.feature != Feature.QUERY:
                raise UntaggedQueryError("session replay widget must tag ClickHouse queries")
            return ([], False, None, None)

        mock_list_recordings.side_effect = assert_tagged

        with override_settings(DEBUG=True, TEST=False):
            result = run_session_replay_list_widget(
                self.team,
                {"limit": 10, "dateRange": {"date_from": "-7d"}},
                user=self.user,
            )

        self.assertEqual(result["limit"], 10)
        mock_list_recordings.assert_called_once()

    @patch("posthog.session_recordings.session_recording_api.list_recordings_from_query")
    def test_session_replay_widget_applies_widget_filter_properties(self, mock_list_recordings: MagicMock) -> None:
        mock_list_recordings.return_value = ([], False, None, None)
        filter_id = "filter-1"

        run_session_replay_list_widget(
            self.team,
            {
                "limit": 5,
                "dateRange": {"date_from": "-7d"},
                "widgetFilters": {
                    filter_id: {
                        "filterId": filter_id,
                        "propertyName": "$browser",
                        "optionId": "opt-1",
                        "operator": "exact",
                        "value": "Chrome",
                    }
                },
            },
            user=self.user,
        )

        query = mock_list_recordings.call_args.kwargs["query"]
        assert query.properties is not None
        assert len(query.properties) == 1
        assert query.properties[0].key == "$browser"
        assert query.properties[0].operator == "exact"
        assert query.properties[0].value == ["Chrome"]

    @staticmethod
    def _saved_filter_for_browser(team: Team, browser: str) -> SessionRecordingPlaylist:
        return SessionRecordingPlaylist.objects.create(
            team=team,
            name="My saved filter",
            type="filters",
            filters={
                "date_from": "-14d",
                "filter_group": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "AND",
                            "values": [{"type": "person", "key": "$browser", "value": [browser], "operator": "exact"}],
                        }
                    ],
                },
                "order": "start_time",
            },
        )

    @staticmethod
    def _widget_browser_filter(browser: str) -> dict[str, Any]:
        return {
            "filter-1": {
                "filterId": "filter-1",
                "propertyName": "$browser",
                "optionId": "opt-1",
                "operator": "exact",
                "value": browser,
            }
        }

    @patch("posthog.session_recordings.session_recording_api.list_recordings_from_query")
    def test_session_replay_widget_uses_saved_filter_as_source_of_truth(self, mock_list_recordings: MagicMock) -> None:
        mock_list_recordings.return_value = ([], False, None, None)
        saved_filter = self._saved_filter_for_browser(self.team, "Firefox")

        run_session_replay_list_widget(
            self.team,
            {
                "limit": 5,
                "orderBy": "click_count",
                "orderDirection": "ASC",
                "savedFilterId": saved_filter.short_id,
                # The widget's own date range and property filters must be ignored.
                "dateRange": {"date_from": "-7d"},
                "widgetFilters": self._widget_browser_filter("Chrome"),
            },
            user=self.user,
        )

        query = mock_list_recordings.call_args.kwargs["query"]
        # Saved filter drives the date range and property filters...
        assert query.date_from == "-14d"
        assert query.properties is not None
        assert len(query.properties) == 1
        assert query.properties[0].key == "$browser"
        assert query.properties[0].value == ["Firefox"]
        # ...while the widget still layers its own sort and limit on top.
        assert query.limit == 5
        assert query.order == RecordingOrder.CLICK_COUNT
        assert query.order_direction == RecordingOrderDirection.ASC

    @patch("posthog.session_recordings.session_recording_api.list_recordings_from_query")
    def test_session_replay_widget_falls_back_when_saved_filter_missing(self, mock_list_recordings: MagicMock) -> None:
        mock_list_recordings.return_value = ([], False, None, None)

        run_session_replay_list_widget(
            self.team,
            {
                "limit": 5,
                "savedFilterId": "does_not_exist",
                "dateRange": {"date_from": "-7d"},
                "widgetFilters": self._widget_browser_filter("Chrome"),
            },
            user=self.user,
        )

        query = mock_list_recordings.call_args.kwargs["query"]
        assert query.properties is not None
        assert query.properties[0].value == ["Chrome"]

    @patch("posthog.session_recordings.session_recording_api.list_recordings_from_query")
    def test_session_replay_widget_ignores_saved_filter_from_other_team(self, mock_list_recordings: MagicMock) -> None:
        mock_list_recordings.return_value = ([], False, None, None)
        other_team = Team.objects.create(organization=self.organization, name="other team")
        saved_filter = self._saved_filter_for_browser(other_team, "Firefox")

        run_session_replay_list_widget(
            self.team,
            {
                "limit": 5,
                "savedFilterId": saved_filter.short_id,
                "dateRange": {"date_from": "-7d"},
                "widgetFilters": self._widget_browser_filter("Chrome"),
            },
            user=self.user,
        )

        query = mock_list_recordings.call_args.kwargs["query"]
        # A saved filter owned by another team must not be reachable; fall back to the widget's filters.
        assert query.properties is not None
        assert query.properties[0].value == ["Chrome"]

    @staticmethod
    def _collection_with_recordings(team: Team, session_ids: list[str]) -> SessionRecordingPlaylist:
        collection = SessionRecordingPlaylist.objects.create(team=team, name="My collection", type="collection")
        for session_id in session_ids:
            recording = SessionRecording.objects.create(team=team, session_id=session_id)
            SessionRecordingPlaylistItem.objects.create(playlist=collection, recording=recording)
        return collection

    @patch("posthog.session_recordings.session_recording_api.list_recordings_from_query")
    def test_session_replay_widget_scopes_to_collection(self, mock_list_recordings: MagicMock) -> None:
        mock_list_recordings.return_value = ([], False, None, None)
        collection = self._collection_with_recordings(self.team, ["session-a", "session-b"])

        run_session_replay_list_widget(
            self.team,
            {
                "limit": 5,
                "orderBy": "click_count",
                "orderDirection": "ASC",
                "collectionId": collection.short_id,
                # The widget's date range still narrows within the collection scope.
                "dateRange": {"date_from": "-7d"},
            },
            user=self.user,
        )

        query = mock_list_recordings.call_args.kwargs["query"]
        # The collection scopes the result set to its pinned recordings...
        assert sorted(query.session_ids) == ["session-a", "session-b"]
        assert query.properties is None
        assert query.date_from == "-7d"
        # ...while the widget still layers its own sort and limit on top.
        assert query.limit == 5
        assert query.order == RecordingOrder.CLICK_COUNT
        assert query.order_direction == RecordingOrderDirection.ASC

    @patch("posthog.session_recordings.session_recording_api.list_recordings_from_query")
    def test_session_replay_widget_collection_skips_legacy_null_recording_items(
        self, mock_list_recordings: MagicMock
    ) -> None:
        mock_list_recordings.return_value = ([], False, None, None)
        collection = self._collection_with_recordings(self.team, ["session-a"])
        # Legacy items used the deprecated session_id field and have a null recording FK.
        SessionRecordingPlaylistItem.objects.create(playlist=collection, recording=None, session_id="legacy")

        run_session_replay_list_widget(
            self.team,
            {"limit": 5, "collectionId": collection.short_id},
            user=self.user,
        )

        query = mock_list_recordings.call_args.kwargs["query"]
        # No None leaks into session_ids — the legacy null-recording item is skipped.
        assert query.session_ids == ["session-a"]

    @patch("products.dashboards.backend.widgets.session_replay_list.UserAccessControl")
    @patch("posthog.session_recordings.session_recording_api.list_recordings_from_query")
    def test_session_replay_widget_skips_collection_without_object_access(
        self, mock_list_recordings: MagicMock, mock_user_access_control: MagicMock
    ) -> None:
        mock_list_recordings.return_value = ([], False, None, None)
        # The user lacks object-level viewer access to the collection.
        mock_user_access_control.return_value.check_access_level_for_object.return_value = False
        collection = self._collection_with_recordings(self.team, ["session-a"])

        run_session_replay_list_widget(
            self.team,
            {
                "limit": 5,
                "collectionId": collection.short_id,
                "widgetFilters": self._widget_browser_filter("Chrome"),
            },
            user=self.user,
        )

        query = mock_list_recordings.call_args.kwargs["query"]
        # An unauthorized collection is treated like a missing one — no session scope, fall back to filters.
        assert query.session_ids is None
        assert query.properties is not None
        assert query.properties[0].value == ["Chrome"]

    @patch("posthog.session_recordings.session_recording_api.list_recordings_from_query")
    def test_session_replay_widget_filters_within_collection(self, mock_list_recordings: MagicMock) -> None:
        mock_list_recordings.return_value = ([], False, None, None)
        collection = self._collection_with_recordings(self.team, ["session-a", "session-b"])

        run_session_replay_list_widget(
            self.team,
            {
                "limit": 5,
                "collectionId": collection.short_id,
                # The widget's own property filters narrow within the collection scope.
                "widgetFilters": self._widget_browser_filter("Chrome"),
            },
            user=self.user,
        )

        query = mock_list_recordings.call_args.kwargs["query"]
        assert sorted(query.session_ids) == ["session-a", "session-b"]
        assert query.properties is not None
        assert query.properties[0].value == ["Chrome"]

    @patch("posthog.session_recordings.session_recording_api.list_recordings_from_query")
    def test_session_replay_widget_combines_collection_and_saved_filter(self, mock_list_recordings: MagicMock) -> None:
        mock_list_recordings.return_value = ([], False, None, None)
        collection = self._collection_with_recordings(self.team, ["session-a", "session-b"])
        saved_filter = self._saved_filter_for_browser(self.team, "Firefox")

        run_session_replay_list_widget(
            self.team,
            {
                "limit": 5,
                "collectionId": collection.short_id,
                "savedFilterId": saved_filter.short_id,
            },
            user=self.user,
        )

        query = mock_list_recordings.call_args.kwargs["query"]
        # The collection scopes the session ids while the saved filter owns the date range and properties.
        assert sorted(query.session_ids) == ["session-a", "session-b"]
        assert query.date_from == "-14d"
        assert query.properties is not None
        assert query.properties[0].value == ["Firefox"]

    @patch("posthog.session_recordings.session_recording_api.list_recordings_from_query")
    def test_session_replay_widget_ignores_collection_from_other_team(self, mock_list_recordings: MagicMock) -> None:
        mock_list_recordings.return_value = ([], False, None, None)
        other_team = Team.objects.create(organization=self.organization, name="other team")
        collection = self._collection_with_recordings(other_team, ["session-a"])

        run_session_replay_list_widget(
            self.team,
            {
                "limit": 5,
                "collectionId": collection.short_id,
                "dateRange": {"date_from": "-7d"},
                "widgetFilters": self._widget_browser_filter("Chrome"),
            },
            user=self.user,
        )

        query = mock_list_recordings.call_args.kwargs["query"]
        # A collection owned by another team must not be reachable; fall back to the widget's filters.
        assert query.session_ids is None
        assert query.properties is not None
        assert query.properties[0].value == ["Chrome"]

    @patch("posthog.session_recordings.session_recording_api.list_recordings_from_query")
    def test_session_replay_widget_falls_back_when_collection_missing(self, mock_list_recordings: MagicMock) -> None:
        mock_list_recordings.return_value = ([], False, None, None)

        run_session_replay_list_widget(
            self.team,
            {
                "limit": 5,
                "collectionId": "does_not_exist",
                "dateRange": {"date_from": "-7d"},
                "widgetFilters": self._widget_browser_filter("Chrome"),
            },
            user=self.user,
        )

        query = mock_list_recordings.call_args.kwargs["query"]
        assert query.session_ids is None
        assert query.properties is not None
        assert query.properties[0].value == ["Chrome"]

    @patch("posthog.session_recordings.session_recording_api.list_recordings_from_query")
    def test_session_replay_widget_attaches_matching_events_query_for_widget_filters(
        self, mock_list_recordings: MagicMock
    ) -> None:
        mock_list_recordings.return_value = ([], False, None, None)

        result = run_session_replay_list_widget(
            self.team,
            {"limit": 5, "dateRange": {"date_from": "-7d"}, "widgetFilters": self._widget_browser_filter("Chrome")},
            user=self.user,
        )

        matching_events_query = result["matchingEventsQuery"]
        assert matching_events_query["kind"] == "RecordingsQuery"
        # session_ids are supplied per recording by the client, not baked into the shipped query.
        assert "session_ids" not in matching_events_query
        assert matching_events_query["properties"][0]["type"] == "event"
        assert matching_events_query["properties"][0]["key"] == "$browser"
        assert matching_events_query["properties"][0]["value"] == ["Chrome"]

    @patch("posthog.session_recordings.session_recording_api.list_recordings_from_query")
    def test_session_replay_widget_attaches_matching_events_query_for_saved_filter_with_events(
        self, mock_list_recordings: MagicMock
    ) -> None:
        mock_list_recordings.return_value = ([], False, None, None)
        saved_filter = SessionRecordingPlaylist.objects.create(
            team=self.team,
            name="Pageview filter",
            type="filters",
            filters={"events": [{"id": "$pageview", "type": "events", "order": 0, "name": "$pageview"}]},
        )

        result = run_session_replay_list_widget(
            self.team,
            {"limit": 5, "savedFilterId": saved_filter.short_id},
            user=self.user,
        )

        matching_events_query = result["matchingEventsQuery"]
        assert matching_events_query["events"][0]["id"] == "$pageview"
        # Same invariant as the widget-filter path: session_ids are supplied per recording by the client.
        assert "session_ids" not in matching_events_query

    @patch("posthog.session_recordings.session_recording_api.list_recordings_from_query")
    def test_session_replay_widget_omits_matching_events_query_without_event_filters(
        self, mock_list_recordings: MagicMock
    ) -> None:
        mock_list_recordings.return_value = ([], False, None, None)

        result = run_session_replay_list_widget(
            self.team,
            {"limit": 5, "dateRange": {"date_from": "-7d"}},
            user=self.user,
        )

        # Nothing to highlight without an event/action/event-property filter, so the query is omitted.
        assert "matchingEventsQuery" not in result

    @patch("posthog.session_recordings.session_recording_api.list_recordings_from_query")
    def test_session_replay_widget_does_not_persist_legacy_filter_conversion(
        self, mock_list_recordings: MagicMock
    ) -> None:
        mock_list_recordings.return_value = ([], False, None, None)
        # A legacy-format playlist (no filter_group) — rendering must not write the converted filters back.
        legacy_filters = {"events": [{"id": "$pageview", "type": "events", "order": 0, "name": "$pageview"}]}
        saved_filter = SessionRecordingPlaylist.objects.create(
            team=self.team, name="Legacy filter", type="filters", filters=legacy_filters
        )

        run_session_replay_list_widget(
            self.team,
            {"limit": 5, "savedFilterId": saved_filter.short_id},
            user=self.user,
        )

        saved_filter.refresh_from_db()
        assert saved_filter.filters == legacy_filters
        assert "filter_group" not in saved_filter.filters

    @patch("posthog.session_recordings.session_recording_api.list_recordings_from_query")
    def test_session_replay_widget_serializes_recordings_with_person(self, mock_list_recordings: MagicMock) -> None:
        person = create_person(team=self.team, properties={"email": "widget-test@example.com"})
        recording = SessionRecording(
            session_id="019e6a07-04fe-792c-b828-49375b8d42e8",
            team=self.team,
            distinct_id="widget-test-distinct",
            duration=120,
        )
        recording.person = person
        mock_list_recordings.return_value = ([recording], False, None, None)

        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dash"})
        _, dashboard_json = self.dashboard_api.create_widget_tile(
            dashboard_id, widget_type="session_replay_list", config={"limit": 10}
        )
        tile_id = dashboard_json["tiles"][0]["id"]

        body = self._run(dashboard_id, [tile_id])

        self.assertIsNone(body["results"][0]["error"])
        self.assertEqual(body["results"][0]["result"]["results"][0]["person"]["name"], "widget-test@example.com")

    @patch("products.dashboards.backend.widgets.session_replay_list._run_recordings_query")
    def test_session_replay_widget_returns_total_count_when_page_has_more(self, mock_run_query: MagicMock) -> None:
        recording = {"id": "recording-1"}

        def run_side_effect(_team: object, query: object, _user: object) -> dict[str, object]:
            limit = query.limit  # type: ignore[attr-defined]
            if limit == 1:
                return {"results": [recording, {**recording, "id": "recording-2"}], "has_next": True}
            return {
                "results": [
                    recording,
                    {**recording, "id": "recording-2"},
                    {**recording, "id": "recording-3"},
                    {**recording, "id": "recording-4"},
                ],
                "has_next": False,
            }

        mock_run_query.side_effect = run_side_effect

        result = run_session_replay_list_widget(
            self.team, {"limit": 1, "dateRange": {"date_from": "-7d"}}, user=self.user
        )

        self.assertTrue(result["hasMore"])
        self.assertEqual(result["totalCount"], 4)
        self.assertFalse(result["totalCountCapped"])
        self.assertEqual(len(result["results"]), 1)
        self.assertEqual(mock_run_query.call_count, 2)
        count_call_query = mock_run_query.call_args_list[1].args[1]
        self.assertEqual(count_call_query.limit, MAX_WIDGET_RESULT_LIMIT)

    @patch("products.dashboards.backend.widgets.error_tracking_list.ErrorTrackingQueryRunner")
    def test_run_widgets_requests_listing_volume_resolution(self, mock_runner_cls: MagicMock) -> None:
        mock_runner_cls.return_value.calculate.return_value = MagicMock(
            model_dump=lambda mode="json": {"results": [], "hasMore": False, "limit": 10, "offset": 0}
        )
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dash"})
        _, dashboard_json = self.dashboard_api.create_widget_tile(dashboard_id, config={"limit": 10})
        tile_id = dashboard_json["tiles"][0]["id"]

        self._run(dashboard_id, [tile_id])

        query = mock_runner_cls.call_args.kwargs["query"]
        self.assertEqual(query.volumeResolution, ERROR_TRACKING_LISTING_VOLUME_RESOLUTION)

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

    @patch("products.dashboards.backend.widgets.error_tracking_list.ErrorTrackingQueryRunner")
    def test_run_error_tracking_list_widget_can_include_total_count(self, mock_runner_cls: MagicMock) -> None:
        issue: dict[str, Any] = {
            "id": "issue-1",
            "name": "TypeError",
            "description": "boom",
            "status": "active",
            "first_seen": "2026-01-01T00:00:00Z",
            "last_seen": "2026-01-02T00:00:00Z",
            "library": "web",
            "source": "app.js",
            "assignee": None,
            "aggregations": {},
        }

        def calculate_side_effect() -> MagicMock:
            query = mock_runner_cls.call_args.kwargs["query"]
            if query.limit == 1:
                return MagicMock(
                    model_dump=lambda mode="json": {
                        "results": [issue, {**issue, "id": "issue-2"}],
                        "hasMore": True,
                        "limit": 1,
                        "offset": 0,
                    }
                )
            return MagicMock(
                model_dump=lambda mode="json": {
                    "results": [issue, {**issue, "id": "issue-2"}, {**issue, "id": "issue-3"}],
                    "hasMore": False,
                    "limit": 25,
                    "offset": 0,
                }
            )

        mock_runner_cls.return_value.calculate.side_effect = calculate_side_effect

        result = run_error_tracking_list_widget(self.team, {"limit": 1}, user=self.user, include_total_count=True)

        self.assertTrue(result["hasMore"])
        self.assertEqual(result["totalCount"], 3)
        self.assertFalse(result["totalCountCapped"])
        self.assertEqual(len(result["results"]), 1)
        self.assertEqual(mock_runner_cls.call_count, 2)
        count_query = mock_runner_cls.call_args_list[1].kwargs["query"]
        self.assertEqual(count_query.limit, MAX_WIDGET_RESULT_LIMIT)

    @patch("products.dashboards.backend.widgets.error_tracking_list.ErrorTrackingQueryRunner")
    def test_run_error_tracking_list_widget_total_count_capped_when_count_hits_limit(
        self, mock_runner_cls: MagicMock
    ) -> None:
        issue: dict[str, Any] = {
            "id": "issue-1",
            "name": "TypeError",
            "description": "boom",
            "status": "active",
            "first_seen": "2026-01-01T00:00:00Z",
            "last_seen": "2026-01-02T00:00:00Z",
            "library": "web",
            "source": "app.js",
            "assignee": None,
            "aggregations": {},
        }

        def calculate_side_effect() -> MagicMock:
            query = mock_runner_cls.call_args.kwargs["query"]
            if query.limit == 1:
                return MagicMock(
                    model_dump=lambda mode="json": {
                        "results": [issue, {**issue, "id": "issue-2"}],
                        "hasMore": True,
                        "limit": 1,
                        "offset": 0,
                    }
                )
            capped_results = [{**issue, "id": f"issue-{index}"} for index in range(MAX_WIDGET_RESULT_LIMIT)]
            return MagicMock(
                model_dump=lambda mode="json": {
                    "results": capped_results,
                    "hasMore": True,
                    "limit": MAX_WIDGET_RESULT_LIMIT,
                    "offset": 0,
                }
            )

        mock_runner_cls.return_value.calculate.side_effect = calculate_side_effect

        result = run_error_tracking_list_widget(self.team, {"limit": 1}, user=self.user, include_total_count=True)

        self.assertTrue(result["hasMore"])
        self.assertEqual(result["totalCount"], MAX_WIDGET_RESULT_LIMIT)
        self.assertTrue(result["totalCountCapped"])
        self.assertEqual(len(result["results"]), 1)
        self.assertEqual(mock_runner_cls.call_count, 2)
        count_query = mock_runner_cls.call_args_list[1].kwargs["query"]
        self.assertEqual(count_query.limit, MAX_WIDGET_RESULT_LIMIT)

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
    def test_disabled_when_feature_flag_off(self, _mock_flag: MagicMock) -> None:
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
            user_access_control: UserAccessControl,
            resource: APIScopeObject,
            required_level: AccessControlLevel = "viewer",
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

    @patch("products.error_tracking.backend.facade.queries.ErrorTrackingQueryRunner.calculate")
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

    @patch("products.error_tracking.backend.facade.queries.ErrorTrackingQueryRunner.calculate")
    @patch("posthog.slo.events.posthoganalytics.capture")
    def test_run_widgets_emits_slo_on_successful_widget_delivery(
        self, mock_capture: MagicMock, mock_calculate: MagicMock
    ) -> None:
        mock_calculate.return_value = MagicMock(
            model_dump=lambda mode="json": {"results": [], "hasMore": False, "limit": 10, "offset": 0}
        )
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dash"})
        _, dashboard_json = self.dashboard_api.create_widget_tile(dashboard_id, config={"limit": 10})
        tile_id = dashboard_json["tiles"][0]["id"]

        self._run(dashboard_id, [tile_id])

        started_calls = [
            call
            for call in mock_capture.call_args_list
            if call.kwargs.get("event") == "slo_operation_started"
            and call.kwargs.get("properties", {}).get("operation") == SloOperation.DASHBOARD_WIDGET_DELIVERY
        ]
        completed_calls = [
            call
            for call in mock_capture.call_args_list
            if call.kwargs.get("event") == "slo_operation_completed"
            and call.kwargs.get("properties", {}).get("operation") == SloOperation.DASHBOARD_WIDGET_DELIVERY
        ]
        self.assertEqual(len(started_calls), 1)
        self.assertEqual(len(completed_calls), 1)
        self.assertEqual(started_calls[0].kwargs["properties"]["widget_type"], "error_tracking_list")
        self.assertEqual(started_calls[0].kwargs["properties"]["dashboard_id"], dashboard_id)
        self.assertEqual(started_calls[0].kwargs["properties"]["tile_id"], tile_id)
        self.assertEqual(completed_calls[0].kwargs["properties"]["outcome"], SloOutcome.SUCCESS)

    @patch("products.dashboards.backend.widgets.error_tracking_list.ErrorTrackingQueryRunner")
    @patch("posthog.slo.events.posthoganalytics.capture")
    def test_run_widgets_emits_slo_failure_when_widget_query_raises(
        self, mock_capture: MagicMock, mock_runner_cls: MagicMock
    ) -> None:
        mock_runner_cls.return_value.calculate.side_effect = Exception("boom")
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dash"})
        _, dashboard_json = self.dashboard_api.create_widget_tile(dashboard_id, config={"limit": 10})
        tile_id = dashboard_json["tiles"][0]["id"]

        self._run(dashboard_id, [tile_id])

        completed_calls = [
            call
            for call in mock_capture.call_args_list
            if call.kwargs.get("event") == "slo_operation_completed"
            and call.kwargs.get("properties", {}).get("operation") == SloOperation.DASHBOARD_WIDGET_DELIVERY
        ]
        self.assertEqual(len(completed_calls), 1)
        self.assertEqual(completed_calls[0].kwargs["properties"]["outcome"], SloOutcome.FAILURE)
        self.assertEqual(completed_calls[0].kwargs["properties"]["widget_type"], "error_tracking_list")
