from datetime import UTC, datetime
from typing import Any

from posthog.test.base import BaseTest, ClickhouseTestMixin

from posthog.schema import DateRange, SessionQuery

from posthog.hogql.constants import MAX_SELECT_TRACES_LIMIT_EXPORT, LimitContext

from posthog.hogql_queries.ai.session_query_runner import SessionQueryRunner
from posthog.models import Team
from posthog.models.ai_events.test_util import bulk_create_ai_events
from posthog.models.event.util import bulk_create_events


def _create_ai_generation_event_in_events_table(
    *,
    team: Team,
    session_id: str,
    trace_id: str,
    distinct_id: str = "person1",
    timestamp: datetime | None = None,
    properties: dict[str, Any] | None = None,
) -> None:
    props = {
        "$ai_session_id": session_id,
        "$ai_trace_id": trace_id,
        "$ai_latency": 1,
        "$ai_input": [{"role": "user", "content": "hello"}],
        "$ai_output_choices": [{"role": "assistant", "content": "hi"}],
        "$ai_input_tokens": 5,
        "$ai_output_tokens": 2,
        "$ai_total_cost_usd": 0.01,
        **(properties or {}),
    }
    bulk_create_events(
        [
            {
                "event": "$ai_generation",
                "distinct_id": distinct_id,
                "properties": props,
                "team": team,
                "timestamp": timestamp,
            }
        ]
    )


def _select_queries_without_metadata(queries: list[str]) -> list[str]:
    return [query for query in queries if "FROM system.columns" not in query]


class TestSessionQueryRunner(ClickhouseTestMixin, BaseTest):
    def test_reads_from_ai_events_without_date_range(self) -> None:
        bulk_create_ai_events(
            [
                {
                    "event": "$ai_generation",
                    "distinct_id": "person1",
                    "team": self.team,
                    "timestamp": datetime(2025, 1, 15, 0, 0, tzinfo=UTC),
                    "properties": {
                        "$ai_session_id": "session-ai-events",
                        "$ai_trace_id": "trace-ai-events",
                        "$ai_latency": 1,
                        "$ai_input": [{"role": "user", "content": "hello"}],
                        "$ai_output_choices": [{"role": "assistant", "content": "hi"}],
                        "$ai_input_tokens": 5,
                        "$ai_output_tokens": 2,
                        "$ai_total_cost_usd": 0.01,
                    },
                }
            ]
        )

        runner = SessionQueryRunner(
            team=self.team,
            query=SessionQuery(sessionId="session-ai-events"),
        )

        with self.capture_select_queries() as queries:
            response = runner.calculate()

        select_queries = _select_queries_without_metadata(queries)
        self.assertEqual(len(select_queries), 1)
        self.assertIn("ai_events", select_queries[0])
        self.assertEqual(len(response.results), 1)
        self.assertEqual(response.results[0].id, "trace-ai-events")
        self.assertEqual(response.results[0].events[0].properties["$ai_input"][0]["content"], "hello")

    def test_paginates_session_traces(self) -> None:
        bulk_create_ai_events(
            [
                {
                    "event": "$ai_generation",
                    "distinct_id": "person1",
                    "team": self.team,
                    "timestamp": datetime(2025, 1, 15, 0, 0, tzinfo=UTC),
                    "properties": {
                        "$ai_session_id": "session-paginated",
                        "$ai_trace_id": "trace-older",
                        "$ai_latency": 1,
                    },
                },
                {
                    "event": "$ai_generation",
                    "distinct_id": "person1",
                    "team": self.team,
                    "timestamp": datetime(2025, 1, 15, 0, 1, tzinfo=UTC),
                    "properties": {
                        "$ai_session_id": "session-paginated",
                        "$ai_trace_id": "trace-newer",
                        "$ai_latency": 1,
                    },
                },
            ]
        )

        first_page = SessionQueryRunner(
            team=self.team,
            query=SessionQuery(sessionId="session-paginated", limit=1),
        ).calculate()
        second_page = SessionQueryRunner(
            team=self.team,
            query=SessionQuery(sessionId="session-paginated", limit=1, offset=1),
        ).calculate()

        self.assertEqual([trace.id for trace in first_page.results], ["trace-newer"])
        self.assertEqual(first_page.hasMore, True)
        self.assertEqual(first_page.limit, 1)
        self.assertEqual(first_page.offset, 0)
        self.assertEqual([trace.id for trace in second_page.results], ["trace-older"])
        self.assertEqual(second_page.hasMore, False)
        self.assertEqual(second_page.limit, 1)
        self.assertEqual(second_page.offset, 1)

    def test_query_limit_uses_default_when_no_limit_specified(self) -> None:
        runner = SessionQueryRunner(
            team=self.team,
            query=SessionQuery(sessionId="session-default-limit"),
        )

        self.assertEqual(runner.paginator.limit, 100)

    def test_query_limit_caps_explicit_session_page_size(self) -> None:
        runner = SessionQueryRunner(
            team=self.team,
            query=SessionQuery(sessionId="session-capped-limit", limit=50000),
        )

        self.assertEqual(runner.paginator.limit, MAX_SELECT_TRACES_LIMIT_EXPORT)

    def test_export_limit_defaults_to_max_when_no_limit_specified(self) -> None:
        runner = SessionQueryRunner(
            team=self.team,
            query=SessionQuery(sessionId="session-export-default-limit"),
            limit_context=LimitContext.EXPORT,
        )

        self.assertEqual(runner.paginator.limit, MAX_SELECT_TRACES_LIMIT_EXPORT)

    def test_includes_sentiment_when_requested(self) -> None:
        generation_id = "generation-session-sentiment"
        bulk_create_ai_events(
            [
                {
                    "event": "$ai_generation",
                    "distinct_id": "person1",
                    "team": self.team,
                    "timestamp": datetime(2025, 1, 15, 0, 0, tzinfo=UTC),
                    "properties": {
                        "$ai_session_id": "session-sentiment",
                        "$ai_trace_id": "trace-sentiment",
                        "$ai_generation_id": generation_id,
                        "$ai_latency": 1,
                        "$ai_input": [{"role": "user", "content": "hello"}],
                        "$ai_output_choices": [{"role": "assistant", "content": "hi"}],
                    },
                },
                {
                    "event": "$ai_evaluation",
                    "distinct_id": "person1",
                    "team": self.team,
                    "timestamp": datetime(2025, 1, 15, 0, 1, tzinfo=UTC),
                    "properties": {
                        "$ai_trace_id": "trace-sentiment",
                        "$ai_evaluation_runtime": "sentiment",
                        "$ai_target_event_id": generation_id,
                        "$ai_sentiment_label": "negative",
                        "$ai_sentiment_score": 0.8,
                        "$ai_sentiment_scores": {"positive": 0.1, "neutral": 0.1, "negative": 0.8},
                        "$ai_sentiment_messages": {
                            "0": {
                                "label": "negative",
                                "score": 0.8,
                                "scores": {"positive": 0.1, "neutral": 0.1, "negative": 0.8},
                            }
                        },
                        "$ai_sentiment_message_count": 1,
                    },
                },
            ]
        )

        response = SessionQueryRunner(
            team=self.team,
            query=SessionQuery(sessionId="session-sentiment", includeSentiment=True),
        ).calculate()

        self.assertEqual(len(response.results), 1)
        trace = response.results[0]
        self.assertIsNotNone(trace.sentiment)
        assert trace.sentiment is not None
        self.assertEqual(trace.sentiment.label, "negative")
        self.assertEqual(trace.sentiment.score, 0.8)
        self.assertIsNotNone(trace.sentiment.messages)
        assert trace.sentiment.messages is not None
        self.assertEqual(trace.sentiment.messages[f"{generation_id}:0"].label, "negative")
        self.assertEqual(len(trace.events), 1)
        self.assertIsNotNone(trace.events[0].sentiment)
        assert trace.events[0].sentiment is not None
        self.assertEqual(trace.events[0].sentiment.label, "negative")
        self.assertIsNotNone(trace.events[0].sentiment.messages)
        assert trace.events[0].sentiment.messages is not None
        self.assertEqual(trace.events[0].sentiment.messages["0"].score, 0.8)

    def test_does_not_fallback_to_events_without_date_range(self) -> None:
        _create_ai_generation_event_in_events_table(
            team=self.team,
            session_id="session-no-bounds",
            trace_id="trace-no-bounds",
            timestamp=datetime(2025, 1, 15, 0, 0, tzinfo=UTC),
        )

        runner = SessionQueryRunner(
            team=self.team,
            query=SessionQuery(sessionId="session-no-bounds"),
        )

        with self.capture_select_queries() as queries:
            response = runner.calculate()

        select_queries = _select_queries_without_metadata(queries)
        self.assertEqual(len(select_queries), 1)
        self.assertIn("ai_events", select_queries[0])
        self.assertEqual(response.results, [])

    def test_falls_back_to_events_with_date_from_only_range(self) -> None:
        _create_ai_generation_event_in_events_table(
            team=self.team,
            session_id="session-date-from",
            trace_id="trace-date-from",
            timestamp=datetime(2025, 1, 15, 0, 0, tzinfo=UTC),
        )

        runner = SessionQueryRunner(
            team=self.team,
            query=SessionQuery(
                sessionId="session-date-from",
                dateRange=DateRange(
                    date_from="2025-01-15T00:00:00Z",
                    explicitDate=True,
                ),
            ),
        )

        with self.capture_select_queries() as queries:
            response = runner.calculate()

        select_queries = _select_queries_without_metadata(queries)
        self.assertEqual(len(select_queries), 2)
        self.assertIn("ai_events", select_queries[0])
        self.assertIn("__ai_events_fallback.timestamp", select_queries[1])
        self.assertEqual(len(response.results), 1)
        self.assertEqual(response.results[0].id, "trace-date-from")
        self.assertEqual(response.results[0].events[0].properties["$ai_output_choices"][0]["content"], "hi")
