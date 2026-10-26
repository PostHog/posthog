import json
import datetime as dt
from typing import Any

from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from posthog.api.snuffle_proxy import SNUFFLE_API_FEATURE_FLAG
from posthog.api.test.dashboards import DashboardAPI

from products.dashboards.backend.api.test.test_experiment_widgets import _InlineExecutor
from products.metrics.backend.facade.testing import seed_metric

GAUGE_QUERY: dict[str, Any] = {
    "kind": "MetricsQuery",
    "clauses": [{"name": "a", "metricName": "cpu_usage", "metricType": "gauge", "aggregation": "max"}],
    "dateRange": {"date_from": "-6h"},
}

HEATMAP_QUERY: dict[str, Any] = {
    "kind": "MetricsQuery",
    "clauses": [{"name": "a", "metricName": "request_duration", "metricType": "histogram"}],
    "dateRange": {"date_from": "-6h"},
    "display": {"type": "heatmap"},
}


class TestMetricsWidget(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.dashboard_api = DashboardAPI(self.client, self.team, self.assertEqual)
        self.enabled_flags = {"dashboard-widgets", "metrics", SNUFFLE_API_FEATURE_FLAG}
        flags_patcher = patch(
            "posthoganalytics.feature_enabled",
            side_effect=lambda flag, *args, **kwargs: flag in self.enabled_flags,
        )
        flags_patcher.start()
        self.addCleanup(flags_patcher.stop)
        executor_patcher = patch("products.dashboards.backend.api.dashboard.ThreadPoolExecutor", _InlineExecutor)
        executor_patcher.start()
        self.addCleanup(executor_patcher.stop)

        now = dt.datetime.now(dt.UTC).replace(second=0, microsecond=0)
        # The value is the age in minutes, so a narrower window shows which points it kept.
        seed_metric(
            team_id=self.team.pk,
            metric_name="cpu_usage",
            points=[(now - dt.timedelta(minutes=age), float(age)) for age in (10, 30, 180)],
        )
        seed_metric(
            team_id=self.team.pk,
            metric_name="request_duration",
            metric_type="histogram",
            points=[(now - dt.timedelta(minutes=10), 6.0)],
            histogram_bounds=[10.0, 100.0],
            histogram_counts=[3, 2, 1],
            count=6,
        )
        self.dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "Service health"})

    def _add_tile(self, query: dict[str, Any] | None = None) -> int:
        config = {} if query is None else {"query": query}
        _, dashboard_json = self.dashboard_api.create_widget_tile(
            self.dashboard_id, widget_type="metrics", config=config
        )
        return dashboard_json["tiles"][-1]["id"]

    def _run(self, tile_id: int, filters_override: dict[str, Any] | None = None) -> dict[str, Any]:
        params: dict[str, str] = {"tile_ids": str(tile_id)}
        if filters_override is not None:
            params["filters_override"] = json.dumps(filters_override)
        response = self.client.get(f"/api/projects/{self.team.id}/dashboards/{self.dashboard_id}/run_widgets/", params)
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        return response.json()["results"][0]

    @staticmethod
    def _values(result: dict[str, Any]) -> list[float]:
        return sorted(
            point["value"]
            for series in result["result"]["results"]
            for point in series["points"]
            if point["value"] is not None
        )

    def test_runs_the_query_and_follows_the_dashboard_date_filter(self) -> None:
        tile_id = self._add_tile(GAUGE_QUERY)

        self.assertEqual(self._values(self._run(tile_id)), [10.0, 30.0, 180.0])
        self.assertEqual(self._values(self._run(tile_id, filters_override={"date_from": "-1h"})), [10.0, 30.0])

    def test_unconfigured_widget_asks_for_a_metric_without_running_a_query(self) -> None:
        tile_id = self._add_tile()

        result = self._run(tile_id)

        self.assertIsNone(result["error"])
        self.assertEqual(result["result"], {"needsConfiguration": True})

    def test_heatmap_display_runs_the_histogram_query(self) -> None:
        tile_id = self._add_tile(HEATMAP_QUERY)

        result = self._run(tile_id)

        self.assertIsNone(result["error"])
        self.assertEqual(result["result"]["bounds"][:2], [10.0, 100.0])
        self.assertTrue(result["result"]["times"])

    @parameterized.expand(
        [
            ("promql", {"clauses": [], "language": "promql", "promql": "up"}, "A heatmap needs a builder query"),
            (
                "gauge metric",
                {"clauses": [{"name": "a", "metricName": "cpu_usage", "metricType": "gauge"}]},
                "A heatmap needs a histogram metric.",
            ),
        ]
    )
    def test_heatmap_display_explains_an_ineligible_query(
        self, _name: str, query_patch: dict[str, Any], expected_error: str
    ) -> None:
        tile_id = self._add_tile({**HEATMAP_QUERY, **query_patch})

        result = self._run(tile_id)

        self.assertIsNone(result["result"])
        self.assertTrue(result["error"].startswith(expected_error), result["error"])
        self.assertTrue(result["error_is_user_facing"])

    @parameterized.expand(
        [
            ("metrics flag off", "metrics", GAUGE_QUERY),
            (
                "PromQL without its flag",
                SNUFFLE_API_FEATURE_FLAG,
                {"clauses": [], "language": "promql", "promql": "up"},
            ),
        ]
    )
    def test_checks_metrics_access_for_every_viewer(self, _name: str, flag: str, query: dict[str, Any]) -> None:
        tile_id = self._add_tile(query)
        self.enabled_flags.discard(flag)

        result = self._run(tile_id)

        self.assertIsNone(result["result"])
        self.assertEqual(result["error"], "You do not have access to metrics.")

    def test_skips_the_shared_widget_throttle_for_signed_in_viewers(self) -> None:
        tile_id = self._add_tile(GAUGE_QUERY)

        with patch(
            "products.dashboards.backend.api.dashboard.get_dashboard_widget_query_throttle_error",
            return_value="Rate limit exceeded. Try again later.",
        ) as throttle:
            result = self._run(tile_id)

        self.assertIsNone(result["error"])
        throttle.assert_not_called()

    def test_cannot_add_a_metrics_widget_without_the_metrics_flag(self) -> None:
        self.enabled_flags.discard("metrics")

        self.dashboard_api.create_widget_tile(
            self.dashboard_id,
            widget_type="metrics",
            config={"query": GAUGE_QUERY},
            expected_status=status.HTTP_400_BAD_REQUEST,
        )
