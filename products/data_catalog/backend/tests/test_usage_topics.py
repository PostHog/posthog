from datetime import UTC, datetime, timedelta

from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events

from django.test import SimpleTestCase

from parameterized import parameterized

from products.data_catalog.backend.facade.contracts import TopicCoverage
from products.data_catalog.backend.facade.enums import FetchOutcome
from products.data_catalog.backend.logic.usage_topics import (
    SessionText,
    build_topic_drafts,
    fetch_topic_sessions,
    session_coverage,
)


def _session(session_id: str, intent: str, *tools: str) -> SessionText:
    return SessionText(session_id=session_id, intent=intent, tools=frozenset(tools))


class TestTopicCoverage(SimpleTestCase):
    @parameterized.expand(
        [
            ("ran_a_metric", ("data-catalog-metric-run", "execute-sql"), {FetchOutcome.SILENT}, "canonical"),
            ("read_then_adapted", ("execute-sql",), {FetchOutcome.ADAPTED, FetchOutcome.SILENT}, "adapted"),
            ("re_derived_without_reading", ("execute-sql",), {FetchOutcome.MISSED}, "silent"),
            ("sql_matching_no_metric", ("execute-sql",), set(), "raw_sql_only"),
            ("query_tool_without_sql", ("query-trends",), set(), "no_sql"),
        ]
    )
    def test_session_coverage(self, _name: str, tools: tuple[str, ...], outcomes: set, expected: str) -> None:
        assert session_coverage(_session("s", "q", *tools), outcomes) == expected

    def test_drafts_skip_unclustered_sessions_and_put_the_largest_topic_first(self) -> None:
        sessions = [
            _session("a", "weekly signups", "execute-sql"),
            _session("b", "signups this week", "data-catalog-metric-run"),
            _session("c", "signups by day", "execute-sql"),
            _session("d", "error rate"),
            _session("e", "embedding failed"),
        ]

        drafts = build_topic_drafts(sessions, [0, 0, 0, 1, None], {"c": {FetchOutcome.SILENT}})

        assert [draft.session_count for draft in drafts] == [3, 1]
        assert drafts[0].coverage == TopicCoverage(canonical=1, adapted=0, silent=1, raw_sql_only=1, no_sql=0)
        assert drafts[0].sample_intents == ("weekly signups", "signups this week", "signups by day")


class TestTopicSessionsQuery(ClickhouseTestMixin, BaseTest):
    def _call(self, session: str, tool: str, intent: str, source: str, at: datetime) -> None:
        _create_event(
            team=self.team,
            event="$mcp_tool_call",
            distinct_id="d1",
            timestamp=at,
            properties={
                "$session_id": session,
                "$mcp_tool_name": tool,
                "$mcp_intent": intent,
                "$mcp_project_id": str(self.team.id),
                "source": source,
            },
        )

    def test_keeps_people_sessions_that_queried_data_with_their_last_intent(self) -> None:
        end = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)
        at = end - timedelta(hours=3)
        self._call("person", "metric-list", "first question", "mcp", at)
        self._call("person", "execute-sql", "last question", "mcp", at + timedelta(minutes=5))
        self._call("person", "execute-sql", "", "mcp", at + timedelta(minutes=6))
        self._call("scout", "execute-sql", "scheduled check", "self_driving", at)
        self._call("wizard", "execute-sql", "set up the project", "wizard", at)
        self._call("silent", "execute-sql", "", "mcp", at)
        self._call("tickets", "conversations-tickets-retrieve", "read the ticket", "mcp", at)
        self._call("trends", "query-trends", "weekly signups", "mcp", at)
        flush_persons_and_events()

        sessions = fetch_topic_sessions(
            team=self.team, telemetry_team=self.team, window_start=end - timedelta(days=1), window_end=end
        )

        assert sorted(sessions, key=lambda session: session.session_id) == [
            _session("person", "last question", "metric-list", "execute-sql"),
            _session("trends", "weekly signups", "query-trends"),
        ]
