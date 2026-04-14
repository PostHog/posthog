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
    cost: float | None = None,
    latency: float | None = None,
    is_error: bool = False,
    timestamp: datetime | None = None,
):
    props: dict = {
        "$ai_trace_id": trace_id,
    }
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
    latency: float | None = None,
    timestamp: datetime | None = None,
):
    props: dict = {
        "$ai_trace_id": trace_id,
        "$ai_span_id": str(uuid.uuid4()),
    }
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
    cost: float | None = None,
    latency: float | None = None,
    timestamp: datetime | None = None,
):
    props: dict = {
        "$ai_trace_id": trace_id,
    }
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
    def _execute_sessions_query(self) -> list[list]:
        query = get_sessions_query(order_by="last_seen", order_direction="DESC")
        response = execute_hogql_query(query, team=self.team)
        return response.results or []

    def _find_session(self, results: list[list], session_id: str) -> list | None:
        for row in results:
            if row[0] == session_id:
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
        # Columns: session_id, traces, spans, generations, embeddings, errors, total_cost, total_latency, first_seen, last_seen
        row = results[0]
        self.assertEqual(row[0], "session-1")
        self.assertEqual(row[1], 2)  # traces
        self.assertEqual(row[2], 1)  # spans
        self.assertEqual(row[3], 2)  # generations
        self.assertEqual(row[4], 1)  # embeddings
        self.assertEqual(row[5], 0)  # errors
        self.assertEqual(row[6], 0.8)  # total_cost: 0.4 + 0.3 + 0.1
        self.assertEqual(row[7], 8.0)  # total_latency: 5.0 + 3.0 (trace-level latencies)

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
        self.assertEqual(session_1[1], 1)  # traces
        self.assertEqual(session_1[3], 1)  # generations
        self.assertEqual(session_1[6], 0.5)  # total_cost

        session_2 = self._find_session(results, "session-2")
        assert session_2 is not None
        self.assertEqual(session_2[1], 1)  # traces
        self.assertEqual(session_2[3], 2)  # generations
        self.assertEqual(session_2[6], 0.5)  # total_cost: 0.2 + 0.3

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
        self.assertEqual(results[0][0], "session-1")
        self.assertEqual(results[0][6], 0.5)  # only the session trace's cost

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
        self.assertEqual(row[5], 2)  # errors: trace + generation both have is_error
        self.assertEqual(row[3], 2)  # generations
        self.assertEqual(row[6], 0.3)  # total_cost: 0.1 + 0.2

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
        self.assertEqual(results[0][7], 4.0)  # latency: 2.5 + 1.5 (fallback to children sum)
