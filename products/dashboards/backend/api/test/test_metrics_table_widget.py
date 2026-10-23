import datetime as dt
from typing import Any

import pytest
from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import patch

from django.test import SimpleTestCase
from django.utils import timezone

from parameterized import parameterized
from rest_framework import status
from rest_framework.exceptions import ValidationError

from posthog.api.test.dashboards import DashboardAPI
from posthog.clickhouse.query_tagging import get_query_tag_value
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.dashboards.backend.constants import METRICS_TABLE_SPARKLINE_POINTS
from products.dashboards.backend.widget_registry import METRICS_TABLE_WIDGET_TYPE, validate_widget_config
from products.metrics.backend.facade.contracts import MetricQueryTooManyRowsError
from products.metrics.backend.facade.testing import seed_metric, truncate_metrics_tables

QUEUE_COLUMN = {"label": "Queue depth", "metricName": "queue_depth", "aggregation": "avg"}
ERRORS_COLUMN = {
    "label": "Errors",
    "metricName": "request_errors",
    "aggregation": "sum",
    "filters": [{"key": "status", "op": "eq", "value": "error"}],
}


class TestMetricsTableWidgetConfig(SimpleTestCase):
    def test_config_defaults_to_unconfigured(self) -> None:
        validated = validate_widget_config(METRICS_TABLE_WIDGET_TYPE, {})
        assert validated.get("groupBy") is None
        assert validated["columns"] == []
        assert validated["limit"] == 25
        assert validated["orderDirection"] == "DESC"

    def test_accepts_a_histogram_quantile_column(self) -> None:
        column = {
            "label": "p95",
            "metricName": "http_server_duration_seconds",
            "aggregation": "histogram_quantile",
            "quantile": 0.95,
        }
        validated = validate_widget_config(METRICS_TABLE_WIDGET_TYPE, {"groupBy": "http.route", "columns": [column]})
        assert validated["columns"][0]["quantile"] == 0.95

    def test_accepts_six_columns_and_a_point_spacing(self) -> None:
        validated = validate_widget_config(
            METRICS_TABLE_WIDGET_TYPE, {"columns": [QUEUE_COLUMN] * 6, "interval": "minute_5"}
        )
        assert len(validated["columns"]) == 6
        assert validated["interval"] == "minute_5"

    @parameterized.expand(
        [
            ("unknown_key", {"evil": True}),
            ("too_many_columns", {"groupBy": "route", "columns": [QUEUE_COLUMN] * 7}),
            ("unknown_interval", {"interval": "minute_7"}),
            ("quantile_missing", {"columns": [{**QUEUE_COLUMN, "aggregation": "histogram_quantile"}]}),
            ("quantile_without_histogram", {"columns": [{**QUEUE_COLUMN, "quantile": 0.5}]}),
            (
                "quantile_out_of_range",
                {"columns": [{**QUEUE_COLUMN, "aggregation": "histogram_quantile", "quantile": 1}]},
            ),
            ("unknown_aggregation", {"columns": [{**QUEUE_COLUMN, "aggregation": "median"}]}),
            (
                "unknown_filter_op",
                {"columns": [{**ERRORS_COLUMN, "filters": [{"key": "a", "op": "gt", "value": "1"}]}]},
            ),
            ("order_column_out_of_range", {"columns": [QUEUE_COLUMN], "orderByColumn": 1}),
            ("limit_above_max", {"limit": 101}),
            ("date_range_wider_than_metrics_queries_allow", {"dateRange": {"date_from": "-90d"}}),
        ]
    )
    def test_rejects_invalid_config(self, _name: str, config: dict[str, Any]) -> None:
        with self.assertRaises(ValidationError):
            validate_widget_config(METRICS_TABLE_WIDGET_TYPE, config)


class TestMetricsTableWidgetRun(ClickhouseTestMixin, APIBaseTest):
    CLASS_DATA_LEVEL_SETUP = True
    now: dt.datetime

    @classmethod
    def setUpTestData(cls) -> None:
        super().setUpTestData()
        truncate_metrics_tables()
        cls.now = timezone.now().replace(second=0, microsecond=0)
        minutes = range(2, 12)
        for route, depth in (("/api/a", 5.0), ("/api/b", 10.0), ("/api/c", 1.0)):
            seed_metric(
                team_id=cls.team.id,
                metric_name="queue_depth",
                points=[(cls.now - dt.timedelta(minutes=m), depth) for m in minutes],
                labels={"route": route},
            )
        # Only /api/b has errors, so the other rows have no value in the errors column.
        for status_value, count in (("error", 3.0), ("ok", 50.0)):
            seed_metric(
                team_id=cls.team.id,
                metric_name="request_errors",
                points=[(cls.now - dt.timedelta(minutes=m), count) for m in minutes],
                labels={"route": "/api/b", "status": status_value},
            )

    def setUp(self) -> None:
        super().setUp()
        self.dashboard_api = DashboardAPI(self.client, self.team, self.assertEqual)
        self.metrics_flag_enabled = True
        flag_patcher = patch(
            "products.dashboards.backend.feature_flags.posthoganalytics.feature_enabled",
            side_effect=lambda flag, *args, **kwargs: flag == "metrics" and self.metrics_flag_enabled,
        )
        flag_patcher.start()
        self.addCleanup(flag_patcher.stop)

    def _create_tile(self, config: dict[str, Any]) -> tuple[int, int]:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "Endpoints"})
        _, dashboard_json = self.dashboard_api.create_widget_tile(
            dashboard_id, widget_type="metrics_table", config=config
        )
        return dashboard_id, dashboard_json["tiles"][0]["id"]

    def _run_tile(self, dashboard_id: int, tile_id: int) -> dict[str, Any]:
        response = self.client.get(
            f"/api/projects/{self.team.id}/dashboards/{dashboard_id}/run_widgets/", {"tile_ids": str(tile_id)}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        return response.json()["results"][0]

    def _run(self, config: dict[str, Any]) -> dict[str, Any]:
        tile_result = self._run_tile(*self._create_tile(config))
        self.assertIsNone(tile_result["error"])
        return tile_result["result"]

    def test_unconfigured_widget_asks_for_configuration(self) -> None:
        result = self._run({})

        assert result["needsConfiguration"] is True
        assert result["rows"] == []

    def test_returns_one_row_per_label_value_sorted_by_the_order_column(self) -> None:
        result = self._run(
            {"groupBy": "route", "columns": [QUEUE_COLUMN, ERRORS_COLUMN], "dateRange": {"date_from": "-1h"}}
        )

        assert result["needsConfiguration"] is False
        assert [column["label"] for column in result["columns"]] == ["Queue depth", "Errors"]
        assert [row["key"] for row in result["rows"]] == ["/api/b", "/api/a", "/api/c"]
        assert [row["values"][0] for row in result["rows"]] == [10.0, 5.0, 1.0]
        assert [row["values"][1] for row in result["rows"]] == [3.0, None, None]
        assert result["totalCount"] == 3
        assert result["hasMore"] is False
        sparkline = result["rows"][0]["sparklines"][0]
        assert len(sparkline) > 1
        assert all(value == 10.0 for value in sparkline if value)

    def test_limit_and_ascending_order_keep_the_lowest_rows(self) -> None:
        result = self._run({"groupBy": "route", "columns": [QUEUE_COLUMN], "orderDirection": "ASC", "limit": 2})

        assert [row["key"] for row in result["rows"]] == ["/api/c", "/api/a"]
        assert result["totalCount"] == 3
        assert result["hasMore"] is True

    def test_existing_tile_stops_returning_metrics_when_the_metrics_flag_is_off(self) -> None:
        dashboard_id, tile_id = self._create_tile({"groupBy": "route", "columns": [QUEUE_COLUMN]})
        self.metrics_flag_enabled = False

        tile_result = self._run_tile(dashboard_id, tile_id)

        assert tile_result["result"] is None
        assert tile_result["error"] is not None

    def test_new_tile_is_rejected_when_the_metrics_flag_is_off(self) -> None:
        self.metrics_flag_enabled = False
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "Endpoints"})

        response = self.client.post(
            f"/api/projects/{self.team.id}/dashboards/{dashboard_id}/widgets/batch/",
            {"widgets": [{"widget_type": METRICS_TABLE_WIDGET_TYPE, "config": {}}]},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content

    @patch("products.metrics.backend.metric_query_runner._ROW_LIMIT", 100)
    def test_many_label_values_over_a_long_range_stay_within_the_row_budget(self) -> None:
        # At the default 6-hour interval, 5 routes over 14 days make 280 bucket rows, above the patched budget.
        for route in ("/a", "/b", "/c", "/d", "/e"):
            seed_metric(
                team_id=self.team.id,
                metric_name="worker_load",
                points=[(self.now - dt.timedelta(hours=6 * step), 1.0) for step in range(56)],
                labels={"route": route},
            )
        column = {"label": "Load", "metricName": "worker_load", "aggregation": "avg"}

        result = self._run({"groupBy": "route", "columns": [column], "dateRange": {"date_from": "-14d"}})

        assert result["totalCount"] == 5
        assert all(len(row["sparklines"][0]) <= METRICS_TABLE_SPARKLINE_POINTS for row in result["rows"])

    def test_widget_query_keeps_the_api_key_access_method_of_the_request(self) -> None:
        dashboard_id, tile_id = self._create_tile({"groupBy": "route", "columns": [QUEUE_COLUMN]})
        token = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="dashboard metrics",
            user=self.user,
            secure_value=hash_key_value(token),
            scopes=["dashboard:read", "query:read", "metrics:read"],
        )
        seen_access_methods: list[str | None] = []

        def record_access_method(**_kwargs: Any) -> list[Any]:
            seen_access_methods.append(get_query_tag_value("access_method"))
            return []

        with patch(
            "products.dashboards.backend.widgets.metrics_table.run_metric_query", side_effect=record_access_method
        ):
            response = self.client.get(
                f"/api/projects/{self.team.id}/dashboards/{dashboard_id}/run_widgets/",
                {"tile_ids": str(tile_id)},
                HTTP_AUTHORIZATION=f"Bearer {token}",
            )

        assert response.status_code == status.HTTP_200_OK, response.content
        assert seen_access_methods == ["personal_api_key"]

    def test_a_column_average_skips_buckets_that_only_another_column_fills(self) -> None:
        seed_metric(
            team_id=self.team.id,
            metric_name="pool_size",
            points=[(self.now - dt.timedelta(minutes=10), 10.0)],
            labels={"route": "/api/pool"},
        )
        seed_metric(
            team_id=self.team.id,
            metric_name="pool_waiters",
            points=[(self.now - dt.timedelta(minutes=40), 4.0)],
            labels={"route": "/api/pool"},
        )
        columns = [
            {"label": "Pool size", "metricName": "pool_size", "aggregation": "avg"},
            {"label": "Waiters", "metricName": "pool_waiters", "aggregation": "avg"},
        ]

        result = self._run({"groupBy": "route", "columns": columns, "dateRange": {"date_from": "-1h"}})

        assert [row["values"] for row in result["rows"]] == [[10.0, 4.0]]

    @patch("products.metrics.backend.metric_query_runner._ROW_LIMIT", 60)
    def test_too_many_label_values_retry_with_fewer_buckets(self) -> None:
        for route in ("/r1", "/r2", "/r3", "/r4", "/r5"):
            seed_metric(
                team_id=self.team.id,
                metric_name="busy_workers",
                points=[(self.now - dt.timedelta(minutes=minute), 2.0) for minute in range(1, 60)],
                labels={"route": route},
            )
        column = {"label": "Busy", "metricName": "busy_workers", "aggregation": "avg"}

        result = self._run({"groupBy": "route", "columns": [column], "dateRange": {"date_from": "-1h"}})

        assert result.get("queryError") is None
        assert result["totalCount"] == 5
        assert [row["values"][0] for row in result["rows"]] == [2.0] * 5

    @parameterized.expand(
        [
            ("histogram", ValueError("histogram bounds differ across the selected series/time range")),
            ("row budget", MetricQueryTooManyRowsError("query produced too many (time bucket, series) rows")),
        ]
    )
    def test_metrics_query_errors_reach_the_tile_as_a_readable_message(self, _name: str, error: Exception) -> None:
        with patch("products.dashboards.backend.widgets.metrics_table.run_metric_query", side_effect=error):
            result = self._run({"groupBy": "route", "columns": [QUEUE_COLUMN]})

        assert result["queryError"] == str(error)
        assert result["rows"] == []

    def test_increase_column_shows_the_same_total_after_the_retry(self) -> None:
        for route in ("/c1", "/c2", "/c3", "/c4", "/c5"):
            seed_metric(
                team_id=self.team.id,
                metric_name="jobs_done_total",
                points=[(self.now - dt.timedelta(minutes=59 - minute), 60.0 * minute) for minute in range(60)],
                labels={"route": route},
                metric_type="sum",
                is_monotonic=True,
            )
        config = {
            "groupBy": "route",
            "columns": [{"label": "Jobs", "metricName": "jobs_done_total", "aggregation": "increase"}],
            "dateRange": {"date_from": "-1h"},
        }

        full_buckets = self._run(config)
        with patch("products.metrics.backend.metric_query_runner._ROW_LIMIT", 60):
            retried = self._run(config)

        assert [row["values"][0] for row in retried["rows"]] == pytest.approx(
            [row["values"][0] for row in full_buckets["rows"]], rel=0.25
        )
