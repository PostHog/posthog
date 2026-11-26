import json
from dataclasses import replace
from datetime import timedelta
from typing import Any

import pytest
from posthog.test.base import BaseTest, ClickhouseTestMixin, patch_clickhouse_client_execute

from parameterized import parameterized

from posthog.schema import HogQLQuery

from posthog.errors import (
    ClickHouseClusterMemoryLimitExceeded,
    ClickHouseEstimatedQueryExecutionTimeTooLong,
    ClickHouseQueryMemoryLimitExceeded,
    ClickHouseQueryTimeOut,
)
from posthog.hogql_queries.hogql_query_runner import HogQLQueryRunner
from posthog.models.event.new_events_schema import use_new_events_schema

from products.ai_observability.backend.logic.traces.trace_metrics import (
    NO_TRACES,
    BucketSize,
    MetricKey,
    bucket_starts,
    tiles_of,
)
from products.ai_observability.backend.logic.traces.trace_metrics_queries import (
    METRICS_QUERY_NAME,
    TraceMetricsRows,
    TraceMetricsTooHeavyError,
    load_trace_metrics,
    metrics_insight_queries,
)
from products.ai_observability.backend.logic.traces.trace_selection import TraceSelection
from products.event_definitions.backend.models import PropertyDefinition
from products.event_definitions.backend.property_type import PropertyType

from .test_trace_selection_queries import CASES, seed, to_selection

PERSON_A = "00000000-0000-4000-8000-0000000000a1"
PERSON_B = "00000000-0000-4000-8000-0000000000b2"
PERSON_ANONYMOUS = "00000000-0000-4000-8000-0000000000c3"
PERSON_ANONYMOUS_ROOT = "00000000-0000-4000-8000-0000000000d4"


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
                # An anonymous root over a generation that names user-b counts user-b, not the root's person.
                {
                    "event": "$ai_trace",
                    "trace_id": "anonymous-root",
                    "minutes": 50,
                    "distinct_id": "anonymous-root",
                    "person_id": PERSON_ANONYMOUS_ROOT,
                },
                {
                    "event": "$ai_generation",
                    "trace_id": "anonymous-root",
                    "minutes": 51,
                    "distinct_id": "user-b",
                    "person_id": PERSON_B,
                },
            ],
        )

        # The new events table stores properties as typed JSON, which keeps no explicit null, so a decline reads as
        # an absent session id there.
        declines = 0 if use_new_events_schema(self.team.pk) else 1
        assert self._load().current == replace(
            NO_TRACES,
            traces=5,
            errored=1,
            cost=1.75,
            sessions=1,
            users=2,
            traces_with_cost=2,
            traces_with_session=2,
            session_declines=declines,
            identified_generations=4,
            non_otel_generations=5,
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
                {"event": "$ai_generation", "trace_id": "fast", "minutes": 30, "properties": {"$ai_latency": 1}},
                {"event": "$ai_generation", "trace_id": "medium", "minutes": 40, "properties": {"$ai_latency": 2}},
            ],
        )

        current = self._load().current

        assert (current.p50_latency_s, current.traces_with_latency, current.traces) == (2, 3, 4)
        assert current.p95_latency_s == pytest.approx(9.2)
        assert current.p99_latency_s == pytest.approx(9.84)

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
            # The window runs from 16:00:00.123 to 18:00 exactly in Kolkata. The spanning trace starts at 15:50 there,
            # and the last trace starts on the window's end.
            ("hourly", BucketSize.HOUR, [1, 3]),
            ("daily", BucketSize.DAY, [4]),
        ]
    )
    def test_metrics_bucket_by_first_timestamp_clamped_to_the_window(
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
                {"event": "$ai_generation", "trace_id": "on-the-end", "minutes": 150, "microseconds": -123456},
            ],
        )
        selection = self._selection(date_from=30, date_to=150)
        window = selection.window
        selection = replace(selection, window=replace(window, end=window.end - timedelta(microseconds=123456)))

        metrics = self._load(selection, size)

        starts = bucket_starts(selection.window, size)
        assert {start: totals.traces for start, totals in metrics.buckets.items()} == dict(
            zip(starts, expected_traces, strict=False)
        )
        assert metrics.current.traces == sum(expected_traces)

    @parameterized.expand(
        [
            ("hourly", BucketSize.HOUR, None),
            ("daily", BucketSize.DAY, None),
            ("session ids typed as numbers", BucketSize.HOUR, PropertyType.Numeric),
        ]
    )
    def test_insight_query_returns_each_tiles_series(
        self, _name: str, size: BucketSize, session_id_type: PropertyType | None
    ) -> None:
        if session_id_type is not None:
            PropertyDefinition.objects.create(
                team=self.team, name="$ai_session_id", property_type=session_id_type, type=PropertyDefinition.Type.EVENT
            )
        seed(
            self.team,
            [
                {
                    "event": "$ai_generation",
                    "trace_id": "spanning",
                    "minutes": -5,
                    "properties": {"$ai_total_cost_usd": 3, "$ai_latency": 2, "$ai_session_id": 100},
                },
                {"event": "$ai_generation", "trace_id": "spanning", "minutes": 5, "properties": {"$ai_is_error": True}},
                {
                    "event": "$ai_generation",
                    "trace_id": "early",
                    "minutes": 10,
                    "distinct_id": "user-a",
                    "person_id": PERSON_A,
                    "properties": {"$ai_total_cost_usd": 0.5, "$ai_session_id": 101, "$ai_latency": 1.5},
                },
                {
                    "event": "$ai_generation",
                    "trace_id": "late",
                    "minutes": 190,
                    "distinct_id": "user-b",
                    "person_id": PERSON_B,
                    "properties": {
                        "$ai_session_id": "00000000-0000-4000-8000-000000000102",
                        "$ai_is_error": True,
                        "$ai_latency": 4,
                    },
                },
                {"event": "$ai_generation", "trace_id": "later", "minutes": 200, "properties": {"$ai_latency": 0.25}},
            ],
        )
        selection = self._selection(date_from=0, date_to=240)
        starts = bucket_starts(selection.window, size)

        rows = self._load(selection, size)

        def rounded(values: list[Any]) -> list[Any]:
            return [None if value is None else round(value, 6) for value in values]

        expected = {
            tile.key: (starts, rounded(tile.series))
            for tile in tiles_of(rows.current, rows.previous, rows.buckets, starts, selection.window)
        }
        results = {
            key: HogQLQueryRunner(query=HogQLQuery(query=query), team=self.team, user=self.user).calculate().results
            for key, query in metrics_insight_queries(self.team, selection, size).items()
        }
        assert {
            key: ([row[0] for row in result], rounded([row[1] for row in result])) for key, result in results.items()
        } == expected
        assert any(value == 0 for value in expected[MetricKey.TRACES][1]) == (size == BucketSize.HOUR)

    def test_metrics_empty_range(self) -> None:
        metrics = self._load()

        assert (metrics.current, metrics.previous, metrics.buckets) == (NO_TRACES, NO_TRACES, {})

    # A session-scoped list skips its counts, so those cases have no list count to match.
    @parameterized.expand([(case["name"], case) for case in CASES if "session_id" not in case["selection"]])
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
