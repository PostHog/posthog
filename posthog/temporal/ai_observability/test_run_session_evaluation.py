import uuid
from datetime import UTC, datetime, timedelta

import pytest

from posthog.schema import LLMTrace, LLMTraceEvent

from posthog.temporal.ai_observability.run_session_evaluation import (
    JUDGE_SESSION_MAX_CHARS,
    build_session_hog_globals,
    format_session_for_judge,
    session_fetch_lookback,
)


def _trace(trace_id: str, *, cost: float, latency: float, event_count: int = 1) -> LLMTrace:
    return LLMTrace.model_validate(
        {
            "id": trace_id,
            "createdAt": datetime.now(UTC).isoformat(),
            "distinctId": "person1",
            "totalCost": cost,
            "totalLatency": latency,
            "events": [
                LLMTraceEvent.model_validate(
                    {
                        "id": str(uuid.uuid4()),
                        "event": "$ai_generation",
                        "createdAt": datetime.now(UTC).isoformat(),
                        "properties": {
                            "$ai_input": [{"role": "user", "content": "hi"}],
                            "$ai_model": "gpt-4",
                            "$ai_latency": 0.5,
                            "$ai_total_cost_usd": 0.002,
                        },
                    }
                )
                for _ in range(event_count)
            ],
        }
    )


class TestSessionFetchLookback:
    @pytest.mark.parametrize(
        "max_age_seconds,expected",
        [
            # Never shorter than the trace lookback, so a short-window session still sees the
            # events that arrived before its first matching generation.
            (60, timedelta(hours=24)),
            (86400, timedelta(hours=24)),
            (7 * 24 * 3600, timedelta(days=7)),
        ],
    )
    def test_covers_the_whole_settle_budget(self, max_age_seconds, expected):
        assert session_fetch_lookback(max_age_seconds) == expected


class TestBuildSessionHogGlobals:
    def test_target_aggregates_across_traces(self):
        traces = [_trace("t1", cost=1.5, latency=2.0), _trace("t2", cost=0.5, latency=3.0)]
        globals_dict = build_session_hog_globals(traces, "s-1")
        assert globals_dict["target"] == {
            "type": "session",
            "id": "s-1",
            "total_cost_usd": 2.0,
            "total_latency_seconds": 5.0,
        }

    def test_evaluation_events_span_every_trace(self):
        traces = [_trace("t1", cost=0, latency=0, event_count=2), _trace("t2", cost=0, latency=0, event_count=3)]
        globals_dict = build_session_hog_globals(traces, "s-1")
        assert len(globals_dict["evaluation_events"]) == 5

    def test_omits_the_trace_only_compatibility_globals(self):
        """`events` and `trace` exist for saved trace-target Hog source. A session eval is new,
        so building them would double the worker memory for nothing."""
        globals_dict = build_session_hog_globals([_trace("t1", cost=0, latency=0)], "s-1")
        assert "events" not in globals_dict
        assert "trace" not in globals_dict

    def test_only_builds_globals_the_bytecode_references(self):
        traces = [_trace("t1", cost=0, latency=0)]
        # Bytecode that reads `target` but not `evaluation_events`.
        globals_dict = build_session_hog_globals(traces, "s-1", bytecode=["_H", 1, 32, "target", 1, 1])
        assert "target" in globals_dict
        assert "evaluation_events" not in globals_dict

    def test_missing_costs_do_not_crash_the_aggregate(self):
        trace = _trace("t1", cost=0, latency=0)
        trace.totalCost = None
        trace.totalLatency = None
        globals_dict = build_session_hog_globals([trace], "s-1")
        assert globals_dict["target"]["total_cost_usd"] == 0
        assert globals_dict["target"]["total_latency_seconds"] == 0


class TestFormatSessionForJudge:
    def test_stays_inside_the_char_budget(self):
        # 260 traces of 100 events each render past JUDGE_SESSION_MAX_CHARS even after the
        # per-trace floor split, because each trace's own rendered text already exceeds the
        # floor; only the final [:JUDGE_SESSION_MAX_CHARS] slice keeps the total in budget.
        traces = [_trace(f"t{i}", cost=0, latency=0, event_count=100) for i in range(260)]
        assert len(format_session_for_judge(traces)) <= JUDGE_SESSION_MAX_CHARS

    def test_every_trace_appears(self):
        traces = [_trace("t-alpha", cost=0, latency=0), _trace("t-beta", cost=0, latency=0)]
        rendered = format_session_for_judge(traces)
        assert "t-alpha" in rendered
        assert "t-beta" in rendered
