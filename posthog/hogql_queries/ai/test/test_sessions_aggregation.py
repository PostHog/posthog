import uuid
from datetime import datetime

from freezegun import freeze_time
from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, _create_person

from posthog.hogql.query import execute_hogql_query

from products.llm_analytics.backend.queries import get_sessions_query


def _create_ai_trace_event(
    *,
    trace_id: str,
    team,
    distinct_id: str = "test-user",
    session_id: str | None = None,
    latency: float | None = None,
    is_error: bool = False,
    timestamp: datetime | None = None,
):
    props: dict = {
        "$ai_trace_id": trace_id,
    }
    if session_id is not None:
        props["$ai_session_id"] = session_id
    if latency is not None:
        props["$ai_latency"] = latency
    if is_error:
        props["$ai_is_error"] = "true"

    _create_event(
        event="$ai_trace",
        distinct_id=distinct_id,
        properties=props,
        team=team,
        timestamp=timestamp,
    )


def _create_ai_generation_event(
    *,
    trace_id: str,
    team,
    distinct_id: str = "test-user",
    session_id: str | None = None,
    cost: float | None = None,
    latency: float | None = None,
    is_error: bool = False,
    timestamp: datetime | None = None,
):
    props: dict = {
        "$ai_trace_id": trace_id,
    }
    if session_id is not None:
        props["$ai_session_id"] = session_id
    if cost is not None:
        props["$ai_total_cost_usd"] = cost
    if latency is not None:
        props["$ai_latency"] = latency
    if is_error:
        props["$ai_is_error"] = "true"

    _create_event(
        event="$ai_generation",
        distinct_id=distinct_id,
        properties=props,
        team=team,
        timestamp=timestamp,
    )


def _create_ai_span_event(
    *,
    trace_id: str,
    team,
    distinct_id: str = "test-user",
    session_id: str | None = None,
    latency: float | None = None,
    timestamp: datetime | None = None,
):
    props: dict = {
        "$ai_trace_id": trace_id,
        "$ai_span_id": str(uuid.uuid4()),
    }
    if session_id is not None:
        props["$ai_session_id"] = session_id
    if latency is not None:
        props["$ai_latency"] = latency

    _create_event(
        event="$ai_span",
        distinct_id=distinct_id,
        properties=props,
        team=team,
        timestamp=timestamp,
    )


def _create_ai_embedding_event(
    *,
    trace_id: str,
    team,
    distinct_id: str = "test-user",
    session_id: str | None = None,
    cost: float | None = None,
    latency: float | None = None,
    timestamp: datetime | None = None,
):
    props: dict = {
        "$ai_trace_id": trace_id,
    }
    if session_id is not None:
        props["$ai_session_id"] = session_id
    if cost is not None:
        props["$ai_total_cost_usd"] = cost
    if latency is not None:
        props["$ai_latency"] = latency

    _create_event(
        event="$ai_embedding",
        distinct_id=distinct_id,
        properties=props,
        team=team,
        timestamp=timestamp,
    )


@freeze_time("2025-01-16T00:00:00Z")
class TestSessionsAggregation(ClickhouseTestMixin, BaseTest):
    def _execute_sessions_query(self) -> list[dict]:
        query = get_sessions_query(order_by="last_seen", order_direction="DESC")
        response = execute_hogql_query(query, team=self.team)
        columns = response.columns or []
        return [dict(zip(columns, row)) for row in (response.results or [])]

    def _find_session(self, results: list[dict], session_id: str) -> dict | None:
        for row in results:
            if row["session_id"] == session_id:
                return row
        return None

    def test_session_aggregates_all_event_types(self):
        _create_person(distinct_ids=["test-user"], team=self.team)

        # Trace 1: trace + generation + span
        _create_ai_trace_event(
            trace_id="trace-1",
            session_id="session-1",
            latency=5.0,
            team=self.team,
            timestamp=datetime(2025, 1, 15, 0, 0),
        )
        _create_ai_generation_event(
            trace_id="trace-1",
            cost=0.4,
            latency=3.0,
            team=self.team,
            timestamp=datetime(2025, 1, 15, 0, 1),
        )
        _create_ai_span_event(
            trace_id="trace-1",
            latency=1.0,
            team=self.team,
            timestamp=datetime(2025, 1, 15, 0, 2),
        )

        # Trace 2: trace + generation + embedding
        _create_ai_trace_event(
            trace_id="trace-2",
            session_id="session-1",
            latency=3.0,
            team=self.team,
            timestamp=datetime(2025, 1, 15, 1, 0),
        )
        _create_ai_generation_event(
            trace_id="trace-2",
            cost=0.3,
            latency=2.0,
            team=self.team,
            timestamp=datetime(2025, 1, 15, 1, 1),
        )
        _create_ai_embedding_event(
            trace_id="trace-2",
            cost=0.1,
            latency=0.5,
            team=self.team,
            timestamp=datetime(2025, 1, 15, 1, 2),
        )

        results = self._execute_sessions_query()

        self.assertEqual(len(results), 1)
        row = results[0]
        self.assertEqual(row["session_id"], "session-1")
        self.assertEqual(row["traces"], 2)
        self.assertEqual(row["spans"], 1)
        self.assertEqual(row["generations"], 2)
        self.assertEqual(row["embeddings"], 1)
        self.assertEqual(row["errors"], 0)
        self.assertEqual(row["total_cost"], 0.8)  # 0.4 + 0.3 + 0.1
        self.assertEqual(row["total_latency"], 8.0)  # 5.0 + 3.0 (trace-level latencies)

    def test_session_aggregates_multiple_sessions(self):
        _create_person(distinct_ids=["test-user"], team=self.team)

        # Session 1: 1 trace with 1 generation
        _create_ai_trace_event(
            trace_id="trace-1",
            session_id="session-1",
            latency=2.0,
            team=self.team,
            timestamp=datetime(2025, 1, 15, 0, 0),
        )
        _create_ai_generation_event(
            trace_id="trace-1",
            cost=0.5,
            team=self.team,
            timestamp=datetime(2025, 1, 15, 0, 1),
        )

        # Session 2: 1 trace with 2 generations
        _create_ai_trace_event(
            trace_id="trace-2",
            session_id="session-2",
            latency=4.0,
            team=self.team,
            timestamp=datetime(2025, 1, 15, 1, 0),
        )
        _create_ai_generation_event(
            trace_id="trace-2",
            cost=0.2,
            team=self.team,
            timestamp=datetime(2025, 1, 15, 1, 1),
        )
        _create_ai_generation_event(
            trace_id="trace-2",
            cost=0.3,
            team=self.team,
            timestamp=datetime(2025, 1, 15, 1, 2),
        )

        results = self._execute_sessions_query()

        self.assertEqual(len(results), 2)

        session_1 = self._find_session(results, "session-1")
        assert session_1 is not None
        self.assertEqual(session_1["traces"], 1)
        self.assertEqual(session_1["generations"], 1)
        self.assertEqual(session_1["total_cost"], 0.5)

        session_2 = self._find_session(results, "session-2")
        assert session_2 is not None
        self.assertEqual(session_2["traces"], 1)
        self.assertEqual(session_2["generations"], 2)
        self.assertEqual(session_2["total_cost"], 0.5)  # 0.2 + 0.3

    def test_traces_without_session_excluded(self):
        _create_person(distinct_ids=["test-user"], team=self.team)

        # Trace with session
        _create_ai_trace_event(
            trace_id="trace-with-session",
            session_id="session-1",
            latency=2.0,
            team=self.team,
            timestamp=datetime(2025, 1, 15, 0, 0),
        )
        _create_ai_generation_event(
            trace_id="trace-with-session",
            cost=0.5,
            team=self.team,
            timestamp=datetime(2025, 1, 15, 0, 1),
        )

        # Trace WITHOUT session
        _create_ai_trace_event(
            trace_id="trace-no-session",
            latency=1.0,
            team=self.team,
            timestamp=datetime(2025, 1, 15, 1, 0),
        )
        _create_ai_generation_event(
            trace_id="trace-no-session",
            cost=0.9,
            team=self.team,
            timestamp=datetime(2025, 1, 15, 1, 1),
        )

        results = self._execute_sessions_query()

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["session_id"], "session-1")
        self.assertEqual(results[0]["total_cost"], 0.5)  # only the session trace's cost

    def test_session_counts_errors(self):
        _create_person(distinct_ids=["test-user"], team=self.team)

        _create_ai_trace_event(
            trace_id="trace-1",
            session_id="session-1",
            is_error=True,
            team=self.team,
            timestamp=datetime(2025, 1, 15, 0, 0),
        )
        _create_ai_generation_event(
            trace_id="trace-1",
            cost=0.1,
            is_error=True,
            team=self.team,
            timestamp=datetime(2025, 1, 15, 0, 1),
        )
        _create_ai_generation_event(
            trace_id="trace-1",
            cost=0.2,
            team=self.team,
            timestamp=datetime(2025, 1, 15, 0, 2),
        )

        results = self._execute_sessions_query()

        self.assertEqual(len(results), 1)
        row = results[0]
        self.assertEqual(row["errors"], 2)  # trace + generation both have is_error
        self.assertEqual(row["generations"], 2)
        self.assertEqual(row["total_cost"], 0.3)  # 0.1 + 0.2

    def test_latency_falls_back_to_children_when_trace_has_no_latency(self):
        _create_person(distinct_ids=["test-user"], team=self.team)

        # Trace without latency
        _create_ai_trace_event(
            trace_id="trace-1",
            session_id="session-1",
            team=self.team,
            timestamp=datetime(2025, 1, 15, 0, 0),
        )
        _create_ai_generation_event(
            trace_id="trace-1",
            latency=2.5,
            team=self.team,
            timestamp=datetime(2025, 1, 15, 0, 1),
        )
        _create_ai_span_event(
            trace_id="trace-1",
            latency=1.5,
            team=self.team,
            timestamp=datetime(2025, 1, 15, 0, 2),
        )

        results = self._execute_sessions_query()

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["total_latency"], 4.0)  # 2.5 + 1.5 (fallback to children sum)

    def test_generation_only_traces_included_in_session(self):
        _create_person(distinct_ids=["test-user"], team=self.team)

        _create_ai_generation_event(
            trace_id="gen-only-trace",
            session_id="session-gen",
            cost=0.5,
            latency=2.0,
            team=self.team,
            timestamp=datetime(2025, 1, 15, 0, 0),
        )
        _create_ai_generation_event(
            trace_id="gen-only-trace",
            session_id="session-gen",
            cost=0.3,
            latency=1.0,
            team=self.team,
            timestamp=datetime(2025, 1, 15, 0, 1),
        )

        results = self._execute_sessions_query()

        self.assertEqual(len(results), 1)
        row = results[0]
        self.assertEqual(row["session_id"], "session-gen")
        self.assertEqual(row["traces"], 1)
        self.assertEqual(row["generations"], 2)
        self.assertEqual(row["total_cost"], 0.8)  # 0.5 + 0.3
        self.assertEqual(row["total_latency"], 3.0)  # 2.0 + 1.0 (sum of children)

    def test_mixed_traces_with_and_without_trace_event(self):
        _create_person(distinct_ids=["test-user"], team=self.team)

        # Trace group 1: has $ai_trace event
        _create_ai_trace_event(
            trace_id="trace-with-parent",
            session_id="session-mix",
            latency=5.0,
            team=self.team,
            timestamp=datetime(2025, 1, 15, 0, 0),
        )
        _create_ai_generation_event(
            trace_id="trace-with-parent",
            cost=0.4,
            team=self.team,
            timestamp=datetime(2025, 1, 15, 0, 1),
        )

        # Trace group 2: no $ai_trace event, only generations
        _create_ai_generation_event(
            trace_id="trace-orphan",
            session_id="session-mix",
            cost=0.2,
            latency=1.5,
            team=self.team,
            timestamp=datetime(2025, 1, 15, 1, 0),
        )

        results = self._execute_sessions_query()

        self.assertEqual(len(results), 1)
        row = results[0]
        self.assertEqual(row["session_id"], "session-mix")
        self.assertEqual(row["traces"], 2)
        self.assertEqual(row["generations"], 2)
        self.assertEqual(row["total_cost"], 0.6)  # 0.4 + 0.2
        self.assertEqual(row["total_latency"], 6.5)  # 5.0 (trace-level) + 1.5 (child fallback)
