import uuid
from datetime import UTC, datetime, timedelta

import pytest
from unittest.mock import Mock, patch

from asgiref.sync import async_to_sync
from temporalio.exceptions import ApplicationError

from posthog.schema import LLMTrace, LLMTraceEvent

from posthog.hogql_queries.ai.ai_table_resolver import AIEventsExpiredError
from posthog.temporal.ai_observability.run_session_evaluation import (
    _MIN_TRACE_CHARS_IN_SESSION,
    _SESSION_EVENT_COUNT_SQL,
    JUDGE_SESSION_MAX_CHARS,
    ExecuteSessionEvaluationInputs,
    SessionFetchOutcome,
    _count_session_events,
    build_session_hog_globals,
    execute_session_hog_eval_activity,
    execute_session_llm_judge_activity,
    fetch_session_for_evaluation,
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
        # Fails loudly if a constant change makes the floor fit inside the budget again, which
        # would leave this test passing without the final slice.
        assert max(JUDGE_SESSION_MAX_CHARS // len(traces), _MIN_TRACE_CHARS_IN_SESSION) * len(traces) > (
            JUDGE_SESSION_MAX_CHARS
        )
        assert len(format_session_for_judge(traces)) <= JUDGE_SESSION_MAX_CHARS

    def test_every_trace_appears(self):
        traces = [_trace("t-alpha", cost=0, latency=0), _trace("t-beta", cost=0, latency=0)]
        rendered = format_session_for_judge(traces)
        assert "t-alpha" in rendered
        assert "t-beta" in rendered


class TestCountSessionEvents:
    def test_the_count_stays_an_ungrouped_aggregate(self):
        """An ungrouped aggregate always returns exactly one row, so `query_ai_events`'s
        empty-result probe never fires and the stripped events-table fallback stays structurally
        unreachable. A GROUP BY or HAVING would let the result come back empty for a session that
        aged out of ai_events, which is what turns "expired" into a judge grading empty content.
        """
        normalized = " ".join(_SESSION_EVENT_COUNT_SQL.split()).upper()
        assert "GROUP BY" not in normalized
        assert "HAVING" not in normalized

    def test_never_falls_back_to_the_stripped_events_table(self):
        with patch(
            "posthog.temporal.ai_observability.run_session_evaluation.query_ai_events",
            return_value=Mock(results=[[7]]),
        ) as mock_query_ai_events:
            count = _count_session_events(Mock(), "s-1", datetime.now(UTC), datetime.now(UTC))

        assert count == 7
        assert mock_query_ai_events.call_args.kwargs["fall_back_to_events"] is False


class TestFetchSessionForEvaluation:
    def test_queries_in_evaluation_mode_with_both_date_bounds(self):
        with (
            patch("posthog.temporal.ai_observability.run_session_evaluation.Team"),
            patch(
                "posthog.temporal.ai_observability.run_session_evaluation._count_session_events",
                return_value=3,
            ),
            patch(
                "posthog.temporal.ai_observability.run_session_evaluation.SessionQueryRunner"
            ) as mock_session_query_runner,
        ):
            mock_session_query_runner.return_value.calculate.return_value = Mock(
                results=[_trace("t1", cost=0, latency=0)]
            )
            fetch_session_for_evaluation(1, "s-1", datetime(2026, 7, 20, tzinfo=UTC), 3600)

        kwargs = mock_session_query_runner.call_args.kwargs
        assert kwargs["for_evaluation"] is True
        assert kwargs["query"].dateRange.date_from is not None
        assert kwargs["query"].dateRange.date_to is not None


class TestExecuteSessionActivities:
    @pytest.mark.parametrize(
        "skip_reason",
        ["session_not_found", "session_too_large", "session_expired"],
    )
    def test_hog_skips_carry_a_session_specific_reason(self, skip_reason):
        with patch(
            "posthog.temporal.ai_observability.run_session_evaluation.fetch_session_for_evaluation",
            return_value=SessionFetchOutcome(traces=None, skip_reason=skip_reason, event_count=0),
        ):
            result = async_to_sync(execute_session_hog_eval_activity)(
                ExecuteSessionEvaluationInputs(
                    evaluation={
                        "evaluation_type": "hog",
                        "evaluation_config": {"bytecode": ["_H", 1, 32, True]},
                        "output_config": {"allows_na": False},
                    },
                    team_id=1,
                    session_id="s-1",
                    window_start=datetime.now(UTC).isoformat(),
                    max_age_seconds=86400,
                )
            )
        assert result["skipped"] is True
        assert result["skip_reason"] == skip_reason
        assert "session" in result["reasoning"].lower()

    def test_judge_rejects_a_non_judge_evaluation(self):
        with pytest.raises(ApplicationError, match="Unsupported evaluation type"):
            execute_session_llm_judge_activity(
                ExecuteSessionEvaluationInputs(
                    evaluation={"evaluation_type": "hog", "output_type": "boolean"},
                    team_id=1,
                    session_id="s-1",
                    window_start=datetime.now(UTC).isoformat(),
                    max_age_seconds=86400,
                )
            )

    def test_hog_reports_an_aged_out_session_as_expired(self):
        with patch(
            "posthog.temporal.ai_observability.run_session_evaluation.fetch_session_for_evaluation",
            side_effect=AIEventsExpiredError(),
        ):
            result = async_to_sync(execute_session_hog_eval_activity)(
                ExecuteSessionEvaluationInputs(
                    evaluation={
                        "evaluation_type": "hog",
                        "evaluation_config": {"bytecode": ["_H", 1, 32, True]},
                        "output_config": {"allows_na": False},
                    },
                    team_id=1,
                    session_id="s-1",
                    window_start=datetime.now(UTC).isoformat(),
                    max_age_seconds=86400,
                )
            )
        assert result["skipped"] is True
        assert result["skip_reason"] == "session_expired"

    def test_judge_reports_an_aged_out_session_as_expired_without_judging(self):
        with (
            patch(
                "posthog.temporal.ai_observability.run_session_evaluation.fetch_session_for_evaluation",
                side_effect=AIEventsExpiredError(),
            ),
            patch("posthog.temporal.ai_observability.run_session_evaluation.call_llm_judge") as mock_call_llm_judge,
        ):
            result = execute_session_llm_judge_activity(
                ExecuteSessionEvaluationInputs(
                    evaluation={
                        "evaluation_type": "llm_judge",
                        "evaluation_config": {"prompt": "Did the user accomplish their goal?"},
                        "output_type": "boolean",
                        "output_config": {"allows_na": False},
                    },
                    team_id=1,
                    session_id="s-1",
                    window_start=datetime.now(UTC).isoformat(),
                    max_age_seconds=86400,
                )
            )
        assert result["skipped"] is True
        assert result["skip_reason"] == "session_expired"
        # The whole point of the fail-loud chain: never grade a transcript stripped of message content.
        mock_call_llm_judge.assert_not_called()

    def test_our_bug_page_names_the_session_target(self):
        unexpected_error = {
            "verdict": None,
            "reasoning": "",
            "error": "Unexpected error during evaluation: KeyError: 'foo'",
            "unexpected": True,
        }
        with (
            patch(
                "posthog.temporal.ai_observability.run_session_evaluation.fetch_session_for_evaluation",
                return_value=SessionFetchOutcome(
                    traces=[_trace("t1", cost=0, latency=0)], skip_reason=None, event_count=1
                ),
            ),
            patch(
                "posthog.temporal.ai_observability.run_session_evaluation.execute_hog_eval_bytecode",
                return_value=unexpected_error,
            ),
        ):
            with pytest.raises(ApplicationError, match=r"Hog evaluation error \(session\)"):
                async_to_sync(execute_session_hog_eval_activity)(
                    ExecuteSessionEvaluationInputs(
                        evaluation={
                            "evaluation_type": "hog",
                            "evaluation_config": {"bytecode": ["_H", 1, 32, True]},
                            "output_config": {"allows_na": False},
                        },
                        team_id=1,
                        session_id="s-1",
                        window_start=datetime.now(UTC).isoformat(),
                        max_age_seconds=86400,
                    )
                )
