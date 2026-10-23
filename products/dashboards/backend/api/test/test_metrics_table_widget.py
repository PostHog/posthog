import datetime as dt
from typing import Any

from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from django.test import SimpleTestCase
from django.utils import timezone

from parameterized import parameterized
from rest_framework import status
from rest_framework.exceptions import ValidationError

from posthog.api.test.dashboards import DashboardAPI

from products.dashboards.backend.widget_registry import METRICS_TABLE_WIDGET_TYPE, validate_widget_config
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

    @parameterized.expand(
        [
            ("unknown_key", {"evil": True}),
            ("too_many_columns", {"groupBy": "route", "columns": [QUEUE_COLUMN] * 5}),
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

    def _run(self, config: dict[str, Any]) -> dict[str, Any]:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "Endpoints"})
        _, dashboard_json = self.dashboard_api.create_widget_tile(
            dashboard_id, widget_type=METRICS_TABLE_WIDGET_TYPE, config=config
        )
        tile_id = dashboard_json["tiles"][0]["id"]
        response = self.client.get(
            f"/api/projects/{self.team.id}/dashboards/{dashboard_id}/run_widgets/", {"tile_ids": str(tile_id)}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        tile_result = response.json()["results"][0]
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
