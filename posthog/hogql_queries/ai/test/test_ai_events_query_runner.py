import pytest
from freezegun import freeze_time
from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event
from unittest.mock import patch

from posthog.schema import AiEventsQuery

from posthog.hogql import ast

from posthog.hogql_queries.ai.ai_events_query_runner import AiEventsQueryRunner

FLAG_ENABLED = patch("posthog.hogql_queries.ai.ai_events_query_runner.is_ai_events_enabled", return_value=True)
FLAG_DISABLED = patch("posthog.hogql_queries.ai.ai_events_query_runner.is_ai_events_enabled", return_value=False)


class TestAiEventsQueryRunner(ClickhouseTestMixin, BaseTest):
    @freeze_time("2026-03-12T12:00:00Z")
    @FLAG_ENABLED
    def test_should_use_ai_events_table_default(self, _mock):
        query = AiEventsQuery(kind="AiEventsQuery", select=["*"])
        runner = AiEventsQueryRunner(query=query, team=self.team)
        assert runner._should_use_ai_events_table() is True

    @freeze_time("2026-03-12T12:00:00Z")
    @FLAG_ENABLED
    def test_should_use_ai_events_table_recent(self, _mock):
        query = AiEventsQuery(kind="AiEventsQuery", select=["*"], after="-24h")
        runner = AiEventsQueryRunner(query=query, team=self.team)
        assert runner._should_use_ai_events_table() is True

    @freeze_time("2026-03-12T12:00:00Z")
    @FLAG_ENABLED
    def test_should_not_use_ai_events_table_for_all(self, _mock):
        query = AiEventsQuery(kind="AiEventsQuery", select=["*"], after="all")
        runner = AiEventsQueryRunner(query=query, team=self.team)
        assert runner._should_use_ai_events_table() is False

    @freeze_time("2026-03-12T12:00:00Z")
    @FLAG_DISABLED
    def test_should_not_use_ai_events_table_when_flag_disabled(self, _mock):
        query = AiEventsQuery(kind="AiEventsQuery", select=["*"], after="-24h")
        runner = AiEventsQueryRunner(query=query, team=self.team)
        assert runner._should_use_ai_events_table() is False

    def test_validate_raises_for_non_ai_events(self):
        query = AiEventsQuery(kind="AiEventsQuery", select=["*"], event="$pageview")
        runner = AiEventsQueryRunner(query=query, team=self.team)
        with pytest.raises(ValueError, match="only supports AI events"):
            runner._validate()

    def test_validate_passes_for_ai_events(self):
        query = AiEventsQuery(kind="AiEventsQuery", select=["*"], event="$ai_generation")
        runner = AiEventsQueryRunner(query=query, team=self.team)
        runner._validate()

    def test_validate_passes_with_no_events(self):
        query = AiEventsQuery(kind="AiEventsQuery", select=["*"])
        runner = AiEventsQueryRunner(query=query, team=self.team)
        runner._validate()

    @freeze_time("2026-03-12T12:00:00Z")
    def test_rewrite_changes_from_clause(self):
        query = AiEventsQuery(kind="AiEventsQuery", select=["*"])
        runner = AiEventsQueryRunner(query=query, team=self.team)
        original = runner._events_runner.to_query()
        rewritten = runner._rewrite_for_ai_events(original)
        assert isinstance(rewritten.select_from, ast.JoinExpr)
        assert isinstance(rewritten.select_from.table, ast.Field)
        assert rewritten.select_from.table.chain == ["ai_events"]

    @freeze_time("2026-03-12T12:00:00Z")
    @FLAG_ENABLED
    def test_to_query_uses_ai_events_within_ttl(self, _mock):
        query = AiEventsQuery(kind="AiEventsQuery", select=["*"], after="-24h")
        runner = AiEventsQueryRunner(query=query, team=self.team)
        query_ast = runner.to_query()
        assert isinstance(query_ast.select_from, ast.JoinExpr)
        assert isinstance(query_ast.select_from.table, ast.Field)
        assert query_ast.select_from.table.chain == ["ai_events"]

    @freeze_time("2026-03-12T12:00:00Z")
    @FLAG_ENABLED
    def test_to_query_uses_events_beyond_ttl(self, _mock):
        query = AiEventsQuery(kind="AiEventsQuery", select=["*"], after="all")
        runner = AiEventsQueryRunner(query=query, team=self.team)
        query_ast = runner.to_query()
        assert isinstance(query_ast.select_from, ast.JoinExpr)
        assert isinstance(query_ast.select_from.table, ast.Field)
        assert query_ast.select_from.table.chain == ["events"]

    @freeze_time("2026-03-12T12:00:00Z")
    @FLAG_ENABLED
    def test_calculate_from_ai_events_table(self, _mock):
        # _create_event writes to `events`; the MV populates `ai_events` automatically.
        _create_event(
            event="$ai_generation",
            distinct_id="user1",
            team=self.team,
            properties={
                "$ai_trace_id": "trace-1",
                "$ai_model": "gpt-4",
                "$ai_input_tokens": 100,
                "$ai_output_tokens": 50,
            },
            timestamp="2026-03-12T11:00:00",
        )

        query = AiEventsQuery(
            kind="AiEventsQuery",
            select=["event", "timestamp"],
            after="-24h",
            event="$ai_generation",
        )
        runner = AiEventsQueryRunner(query=query, team=self.team)
        result = runner.calculate()
        assert len(result.results) == 1
        assert result.results[0][0] == "$ai_generation"

    @freeze_time("2026-03-12T12:00:00Z")
    @FLAG_ENABLED
    def test_should_not_use_ai_events_table_before_beyond_ttl(self, _mock):
        query = AiEventsQuery(kind="AiEventsQuery", select=["*"], before="2026-01-01")
        runner = AiEventsQueryRunner(query=query, team=self.team)
        assert runner._should_use_ai_events_table() is False

    @freeze_time("2026-03-12T12:00:00Z")
    @FLAG_ENABLED
    def test_should_use_ai_events_table_before_within_ttl(self, _mock):
        query = AiEventsQuery(kind="AiEventsQuery", select=["*"], before="-5d")
        runner = AiEventsQueryRunner(query=query, team=self.team)
        assert runner._should_use_ai_events_table() is True

    @freeze_time("2026-03-12T12:00:00Z")
    @FLAG_ENABLED
    def test_calculate_fallback_to_events_table(self, _mock):
        _create_event(
            event="$ai_generation",
            distinct_id="user1",
            team=self.team,
            properties={
                "$ai_trace_id": "trace-1",
                "$ai_model": "gpt-4",
            },
            timestamp="2026-03-12T11:00:00",
        )

        query = AiEventsQuery(
            kind="AiEventsQuery",
            select=["event", "timestamp"],
            after="all",
            event="$ai_generation",
        )
        runner = AiEventsQueryRunner(query=query, team=self.team)
        result = runner.calculate()
        assert len(result.results) == 1
        assert result.results[0][0] == "$ai_generation"

    @freeze_time("2026-03-12T12:00:00Z")
    @FLAG_DISABLED
    def test_to_query_falls_back_to_events_when_flag_disabled(self, _mock):
        query = AiEventsQuery(kind="AiEventsQuery", select=["*"], after="-24h")
        runner = AiEventsQueryRunner(query=query, team=self.team)
        query_ast = runner.to_query()
        assert isinstance(query_ast.select_from, ast.JoinExpr)
        assert isinstance(query_ast.select_from.table, ast.Field)
        assert query_ast.select_from.table.chain == ["events"]
