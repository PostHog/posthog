import json
from dataclasses import replace
from typing import Any

import pytest
from posthog.test.base import BaseTest, ClickhouseTestMixin, patch_clickhouse_client_execute

from parameterized import parameterized

from posthog.errors import (
    ClickHouseClusterMemoryLimitExceeded,
    ClickHouseEstimatedQueryExecutionTimeTooLong,
    ClickHouseQueryMemoryLimitExceeded,
    ClickHouseQueryTimeOut,
)
from posthog.models.event.new_events_schema import use_new_events_schema

from products.ai_observability.backend.logic.traces.trace_metrics import NO_TRACES, BucketSize, bucket_starts
from products.ai_observability.backend.logic.traces.trace_metrics_queries import (
    METRICS_QUERY_NAME,
    TraceMetricsRows,
    TraceMetricsTooHeavyError,
    load_trace_metrics,
)
from products.ai_observability.backend.logic.traces.trace_selection import TraceSelection

from .test_trace_selection_queries import CASES, seed, to_selection

PERSON_A = "00000000-0000-4000-8000-0000000000a1"
PERSON_B = "00000000-0000-4000-8000-0000000000b2"
PERSON_ANONYMOUS = "00000000-0000-4000-8000-0000000000c3"


def _per_query_memory_limit() -> ClickHouseQueryMemoryLimitExceeded:
    error = ClickHouseQueryMemoryLimitExceeded()
    error.is_per_query_limit = True
    return error


class TestTraceMetricsQueries(ClickhouseTestMixin, BaseTest):
    def setUp(self) -> None:
        super().setUp()
        # Away from UTC, a bucket floored in UTC instead of the project's zone lands half an hour off.
        self.team.timezone = "Asia/Kolkata"
        self.team.save()

    def _selection(self, **overrides: Any) -> TraceSelection:
        return to_selection(self.team, {"date_from": 0, "date_to": 120, **overrides})

    def _load(self, selection: TraceSelection | None = None, size: BucketSize = BucketSize.HOUR) -> TraceMetricsRows:
        return load_trace_metrics(self.team, self.user, selection or self._selection(), size)

    def test_metrics_counts_cost_errors_sessions_users(self) -> None:
        seed(
            self.team,
            [
                {
                    "event": "$ai_generation",
                    "trace_id": "failed",
                    "minutes": 10,
                    "distinct_id": "user-a",
                    "person_id": PERSON_A,
                    "properties": {"$ai_total_cost_usd": 0.5, "$ai_session_id": "session-1", "$ai_is_error": True},
                },
                {
                    "event": "$ai_embedding",
                    "trace_id": "failed",
                    "minutes": 11,
                    "distinct_id": "user-a",
                    "person_id": PERSON_A,
                    "properties": {"$ai_total_cost_usd": 0.25},
                },
                {
                    "event": "$ai_span",
                    "trace_id": "failed",
                    "minutes": 12,
                    "distinct_id": "user-a",
                    "person_id": PERSON_A,
                    "properties": {"$ai_total_cost_usd": 9},
                },
                {
                    "event": "$ai_generation",
                    "trace_id": "costly",
                    "minutes": 20,
                    "distinct_id": "user-b",
                    "person_id": PERSON_B,
                    "properties": {"$ai_total_cost_usd": 1.0, "$ai_session_id": "session-1"},
                },
                {
                    "event": "$ai_generation",
                    "trace_id": "free",
                    "minutes": 30,
                    "distinct_id": "user-a",
                    "person_id": PERSON_A,
                    "properties": {"$ai_session_id": ""},
                },
                {
                    "event": "$ai_generation",
                    "trace_id": "free",
                    "minutes": 31,
                    "distinct_id": "free",
                    "properties": {"$ai_ingestion_source": "otel"},
                },
                # Distinct id equal to the trace id: an anonymous person, and a declined session.
                {
                    "event": "$ai_generation",
                    "trace_id": "anonymous",
                    "minutes": 40,
                    "distinct_id": "anonymous",
                    "person_id": PERSON_ANONYMOUS,
                    "properties": {"$ai_session_id": None},
                },
                # Feedback carries a real user id, which identifies neither the trace nor the project's users.
                {"event": "$ai_feedback", "trace_id": "anonymous", "minutes": 41, "distinct_id": "user-c"},
            ],
        )

        # The new events table stores properties as typed JSON, which keeps no explicit null, so a decline reads as
        # an absent session id there.
        declines = 0 if use_new_events_schema(self.team.pk) else 1
        assert self._load().current == replace(
            NO_TRACES,
            traces=4,
            errored=1,
            cost=1.75,
            sessions=1,
            users=2,
            traces_with_cost=2,
            traces_with_session=2,
            session_declines=declines,
            identified_generations=3,
            non_otel_generations=4,
        )

    def test_metrics_p95_uses_trace_latency(self) -> None:
        seed(
            self.team,
            [
                {"event": "$ai_trace", "trace_id": "rooted", "minutes": 10, "properties": {"$ai_latency": 10}},
                {
                    "event": "$ai_generation",
                    "trace_id": "rooted",
                    "minutes": 10,
                    "properties": {"$ai_latency": 3, "$ai_parent_id": "rooted"},
                },
                {"event": "$ai_generation", "trace_id": "untimed", "minutes": 20},
            ],
        )

        current = self._load().current

        assert (current.p95_latency_s, current.traces_with_latency, current.traces) == (10, 1, 2)

    def test_metrics_split_current_and_previous(self) -> None:
        seed(
            self.team,
            [
                {"event": "$ai_generation", "trace_id": "before-both", "minutes": -200},
                {"event": "$ai_generation", "trace_id": "previous", "minutes": -30},
                {"event": "$ai_generation", "trace_id": "spanning", "minutes": -5},
                {"event": "$ai_generation", "trace_id": "spanning", "minutes": 5, "properties": {"$ai_is_error": True}},
                {"event": "$ai_generation", "trace_id": "current", "minutes": 30},
                # Each period reads only 10 minutes past its own bounds, so the previous read sees only the -30 event,
                # and the current period takes none of its error, cost or session.
                {
                    "event": "$ai_generation",
                    "trace_id": "spanning-wide",
                    "minutes": -30,
                    "properties": {"$ai_is_error": True, "$ai_total_cost_usd": 2.5, "$ai_session_id": "session-1"},
                },
                {"event": "$ai_generation", "trace_id": "spanning-wide", "minutes": 20},
                {"event": "$ai_generation", "trace_id": "rated-after-start", "minutes": -40},
                {"event": "$ai_feedback", "trace_id": "rated-after-start", "minutes": 5},
            ],
        )

        metrics = self._load()

        assert (
            metrics.current.traces,
            metrics.current.errored,
            metrics.current.cost,
            metrics.current.sessions,
            metrics.previous.traces,
            metrics.previous.errored,
        ) == (3, 1, 0, 0, 2, 0)

    @parameterized.expand(
        [
            # The window starts at 16:00:00.123 in Kolkata, and the spanning trace starts at 15:50 there.
            ("hourly", BucketSize.HOUR, [1, 2]),
            ("daily", BucketSize.DAY, [3]),
        ]
    )
    def test_metrics_bucket_by_first_timestamp_clamped_to_window_start(
        self, _name: str, size: BucketSize, expected_traces: list[int]
    ) -> None:
        seed(
            self.team,
            [
                {"event": "$ai_generation", "trace_id": "previous", "minutes": 0},
                {"event": "$ai_generation", "trace_id": "spanning", "minutes": 20},
                {"event": "$ai_generation", "trace_id": "spanning", "minutes": 35},
                {"event": "$ai_generation", "trace_id": "later", "minutes": 100},
                {"event": "$ai_generation", "trace_id": "later-too", "minutes": 110},
            ],
        )
        selection = self._selection(date_from=30, date_to=150)

        metrics = self._load(selection, size)

        starts = bucket_starts(selection.window, size)
        assert {start: totals.traces for start, totals in metrics.buckets.items()} == dict(
            zip(starts, expected_traces, strict=False)
        )
        assert metrics.current.traces == sum(expected_traces)

    def test_metrics_empty_range(self) -> None:
        metrics = self._load()

        assert (metrics.current, metrics.previous, metrics.buckets) == (NO_TRACES, NO_TRACES, {})

    @parameterized.expand([(case["name"], case) for case in CASES])
    def test_metrics_match_list_counts(self, _name: str, case: dict[str, Any]) -> None:
        if "team_test_account_filters" in case:
            self.team.test_account_filters = case["team_test_account_filters"]
        self.team.test_account_filters_default_checked = case.get("team_test_account_filters_default_checked", False)
        self.team.save()
        seed(self.team, case["events"])

        current = self._load(to_selection(self.team, case["selection"])).current

        assert (current.traces, current.errored) == (
            case["expected_counts"]["total"],
            case["expected_counts"]["errors"],
        )

    @parameterized.expand(
        [
            ("timeout", ClickHouseQueryTimeOut()),
            ("estimated too long", ClickHouseEstimatedQueryExecutionTimeTooLong()),
            ("per-query memory", _per_query_memory_limit()),
        ]
    )
    def test_metrics_too_heavy_maps_limit_errors(self, _name: str, error: Exception) -> None:
        def fail(_execute: Any, _query: str, *_args: Any, **_kwargs: Any) -> Any:
            raise error

        with patch_clickhouse_client_execute(fail), pytest.raises(TraceMetricsTooHeavyError):
            self._load()

    def test_cluster_memory_pressure_is_not_too_heavy(self) -> None:
        def fail(_execute: Any, _query: str, *_args: Any, **_kwargs: Any) -> Any:
            raise ClickHouseClusterMemoryLimitExceeded()

        with patch_clickhouse_client_execute(fail), pytest.raises(ClickHouseClusterMemoryLimitExceeded):
            self._load()

    def test_the_read_is_one_tagged_grouping_sets_query(self) -> None:
        reads: list[tuple[dict[str, Any], str]] = []

        def record(execute: Any, query: str, *args: Any, **kwargs: Any) -> Any:
            tags = json.loads((kwargs.get("settings") or {}).get("log_comment", "{}"))
            if tags.get("name") and "FROM system.columns" not in query:
                reads.append((tags, query))
            return execute(query, *args, **kwargs)

        with patch_clickhouse_client_execute(record):
            self._load()

        [(tags, query)] = reads
        assert (tags["name"], tags["product"]) == (METRICS_QUERY_NAME, "llm_analytics")
        self.assertQueryMatchesSnapshot(query)
