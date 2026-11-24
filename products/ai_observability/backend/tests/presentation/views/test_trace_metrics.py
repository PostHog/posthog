from datetime import timedelta

import time_machine
from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import patch

from django.core.cache import cache

from parameterized import parameterized

from posthog.hogql.errors import ExposedHogQLError

from posthog.errors import ExposedCHQueryError

from products.ai_observability.backend.facade import api

from .trace_fixtures import T0, TraceEvents


@time_machine.travel(T0 + timedelta(hours=2), tick=False)
class TestTraceMetricsViewSet(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        cache.clear()

    def _get(self, params: dict[str, str] | None = None, *, scopes: list[str] | None = None):
        headers = {}
        if scopes is not None:
            self.client.logout()
            headers["authorization"] = f"Bearer {self.create_personal_api_key_with_scopes(scopes)}"
        return self.client.get(
            f"/api/projects/{self.team.id}/ai_observability/traces/metrics/", params or {}, headers=headers
        )

    def test_metrics_returns_contract_shape(self) -> None:
        events = TraceEvents(self.team)
        events.add("trace-1")
        events.seed()

        response = self._get({"date_from": "-3h", "filter_test_accounts": "false"})

        assert response.status_code == 200, response.json()
        body = response.json()
        assert set(body) == {
            "dateFrom",
            "dateTo",
            "previousDateFrom",
            "previousDateTo",
            "bucketSize",
            "bucketStarts",
            "tiles",
        }
        assert body["bucketSize"] == "hour"
        assert [tile["key"] for tile in body["tiles"]] == [
            "cost",
            "users",
            "sessions",
            "traces",
            "error_rate",
            "p95_latency",
        ]
        traces_tile = next(tile for tile in body["tiles"] if tile["key"] == "traces")
        assert (traces_tile["label"], traces_tile["value"], traces_tile["status"], traces_tile["setupLabel"]) == (
            "Traces",
            1,
            "ok",
            None,
        )
        assert len(traces_tile["series"]) == len(body["bucketStarts"])
        assert sum(traces_tile["series"]) == 1

    @parameterized.expand(
        [
            ("unparseable date", {"date_from": "not-a-date"}),
            ("range ending before it starts", {"date_from": "-1h", "date_to": "-3h"}),
        ]
    )
    def test_metrics_invalid_window_is_400(self, _name: str, params: dict[str, str]) -> None:
        assert self._get(params).status_code == 400

    def test_metrics_too_heavy_is_422_with_code(self) -> None:
        with patch(
            "products.ai_observability.backend.logic.traces.trace_metrics_queries.load_trace_metrics",
            side_effect=api.TraceMetricsTooHeavyError(),
        ):
            response = self._get()

        assert (response.status_code, response.json()) == (
            422,
            {"detail": "This range is too long to compute. Try a shorter one.", "code": "range_too_long"},
        )

    @parameterized.expand(
        [
            ("a failing custom filter in hogql", ExposedHogQLError("bad filter")),
            ("a rejected clickhouse query", ExposedCHQueryError("bad query")),
        ]
    )
    def test_metrics_query_errors_the_caller_can_fix_are_400(self, _name: str, error: Exception) -> None:
        with patch(
            "products.ai_observability.backend.logic.traces.trace_metrics_queries.load_trace_metrics",
            side_effect=error,
        ):
            assert self._get().status_code == 400

    @parameterized.expand([("read key", ["llm_analytics:read"], 200), ("another scope", ["insight:read"], 403)])
    def test_metrics_requires_read_scope(self, _name: str, scopes: list[str], expected_status: int) -> None:
        assert self._get(scopes=scopes).status_code == expected_status
