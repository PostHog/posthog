"""Tests for the migrated `fetch_trace` in the trace-summarization Temporal pipeline.

Covers the strip-migration contract: heavy columns must come back populated on
the dedicated path (post-strip rows are only readable there) and the function
must hand back a fully-formed LLMTrace, not raise.
"""

import pytest
from unittest.mock import MagicMock, patch

from posthog.schema import LLMTrace, TraceQueryResponse

from posthog.temporal.llm_analytics.trace_summarization.queries import fetch_trace


@pytest.fixture
def team(db):
    from posthog.models.organization import Organization
    from posthog.models.team import Team

    organization = Organization.objects.create(name="Test Org")
    return Team.objects.create(organization=organization, name="Test Team")


def _make_trace(trace_id: str, events: list | None = None) -> LLMTrace:
    return LLMTrace(
        id=trace_id,
        createdAt="2026-04-27T07:00:00+00:00",
        distinctId="d1",
        events=events or [],
    )


@pytest.mark.django_db
class TestFetchTrace:
    def test_returns_llmtrace_when_runner_has_results(self, team):
        trace = _make_trace("trace-abc")
        with patch("posthog.temporal.llm_analytics.trace_summarization.queries.TraceQueryRunner") as mock_runner_cls:
            mock_runner = MagicMock()
            mock_runner.calculate.return_value = TraceQueryResponse(results=[trace])
            mock_runner_cls.return_value = mock_runner

            result = fetch_trace(team, "trace-abc", "2026-04-27T07:00:00+00:00", "2026-04-27T08:00:00+00:00")

            assert result is not None
            assert result.id == "trace-abc"
            # Runner was instantiated with the team and a TraceQuery scoped to that trace.
            args, kwargs = mock_runner_cls.call_args
            assert kwargs["team"] is team
            assert kwargs["query"].traceId == "trace-abc"
            # Date range is forwarded raw — TraceQueryDateRange handles ±10min widening.
            assert kwargs["query"].dateRange.date_from == "2026-04-27T07:00:00+00:00"
            assert kwargs["query"].dateRange.date_to == "2026-04-27T08:00:00+00:00"

    def test_returns_none_when_runner_has_no_results(self, team):
        with patch("posthog.temporal.llm_analytics.trace_summarization.queries.TraceQueryRunner") as mock_runner_cls:
            mock_runner = MagicMock()
            mock_runner.calculate.return_value = TraceQueryResponse(results=[])
            mock_runner_cls.return_value = mock_runner

            result = fetch_trace(team, "missing-trace", "2026-04-27T07:00:00+00:00", "2026-04-27T08:00:00+00:00")
            assert result is None

    def test_runner_handles_post_strip_heavy_columns(self, team):
        """Smoke-checks the contract that the runner's response surfaces heavy
        props on the events under `properties.$ai_input`. Real merge logic is
        tested in `test_trace_query_runner.py`; here we just assert this
        function returns whatever the runner produces unchanged."""
        from posthog.schema import LLMTraceEvent

        event_with_heavy = LLMTraceEvent(
            id="evt-1",
            event="$ai_generation",
            createdAt="2026-04-27T07:00:00+00:00",
            properties={"$ai_input": [{"role": "user", "content": "hi"}]},
        )
        trace = _make_trace("trace-1", events=[event_with_heavy])

        with patch("posthog.temporal.llm_analytics.trace_summarization.queries.TraceQueryRunner") as mock_runner_cls:
            mock_runner = MagicMock()
            mock_runner.calculate.return_value = TraceQueryResponse(results=[trace])
            mock_runner_cls.return_value = mock_runner

            result = fetch_trace(team, "trace-1", "2026-04-27T07:00:00+00:00", "2026-04-27T08:00:00+00:00")

            assert result is not None
            assert len(result.events) == 1
            assert result.events[0].properties["$ai_input"] == [{"role": "user", "content": "hi"}]
