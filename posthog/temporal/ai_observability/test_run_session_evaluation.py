import uuid
from datetime import UTC, datetime, timedelta

import pytest
from freezegun import freeze_time
from unittest.mock import Mock, patch

from asgiref.sync import async_to_sync
from temporalio.exceptions import ApplicationError

from posthog.schema import LLMTrace, LLMTraceEvent

from posthog.hogql.constants import MAX_SELECT_TRACES_LIMIT_EXPORT

from posthog.temporal.ai_observability.evaluation_payload import payload_budget_bytes
from posthog.temporal.ai_observability.run_session_evaluation import (
    _SESSION_EVENT_COUNT_SQL,
    AI_EVENTS_RETENTION_DAYS,
    JUDGE_SESSION_MAX_CHARS,
    ExecuteSessionEvaluationInputs,
    SessionFetchOutcome,
    _count_session_events,
    _SessionEventCount,
    build_session_hog_globals,
    execute_session_hog_eval_activity,
    execute_session_llm_judge_activity,
    fetch_session_for_evaluation,
    format_session_for_judge,
    session_fetch_lookback,
)

FROZEN_NOW = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)


def _trace(
    trace_id: str, *, cost: float, latency: float, event_count: int = 1, created_at: datetime | None = None
) -> LLMTrace:
    return LLMTrace.model_validate(
        {
            "id": trace_id,
            "createdAt": (created_at or datetime.now(UTC)).isoformat(),
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
    def test_returns_none_rather_than_silently_dropping_trailing_traces(self):
        # A final [:JUDGE_SESSION_MAX_CHARS] slice would drop the closing traces with no marker, so
        # the caller must skip the session instead of judging a partial transcript.
        traces = [_trace(f"t{i}", cost=0, latency=0, event_count=100) for i in range(260)]
        assert format_session_for_judge(traces) is None

    def test_many_small_traces_are_judged_rather_than_skipped_on_count_alone(self):
        """The overflow check must measure the rendered transcript, not `per_trace_budget * n`.
        The product form made this a hard cliff at 251 traces however little they contained, so a
        long thin conversation was skipped while its content sat far inside the budget.
        """
        traces = [_trace(f"t{i}", cost=0, latency=0) for i in range(400)]
        rendered = format_session_for_judge(traces)
        assert rendered is not None
        assert len(rendered) <= JUDGE_SESSION_MAX_CHARS
        assert "t399" in rendered

    def test_every_trace_appears(self):
        traces = [_trace("t-alpha", cost=0, latency=0), _trace("t-beta", cost=0, latency=0)]
        rendered = format_session_for_judge(traces)
        assert rendered is not None
        assert "t-alpha" in rendered
        assert "t-beta" in rendered


@freeze_time(FROZEN_NOW)
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

    def test_counts_the_rows_the_fetch_will_read_not_just_the_tagged_ones(self):
        """`MAX_SESSION_EVAL_EVENTS` only bounds the payload if the preflight and
        `SessionQueryRunner._build_query` select the same rows. The runner reads six event types and
        resolves traces first, then reads every event of those traces — `session_id` is per-event and
        nullable, so a producer that tags only the trace root would otherwise preflight at 1 while
        the fetch reads the whole trace.
        """
        normalized = " ".join(_SESSION_EVENT_COUNT_SQL.split())
        for event in ("$ai_span", "$ai_generation", "$ai_embedding", "$ai_metric", "$ai_feedback", "$ai_trace"):
            assert f"'{event}'" in normalized
        assert "trace_id IN (" in normalized
        assert "session_id = {session_id}" in normalized

    def test_never_falls_back_to_the_stripped_events_table(self):
        first_seen = datetime(2026, 7, 1, tzinfo=UTC)
        with patch(
            "posthog.temporal.ai_observability.run_session_evaluation.query_ai_events",
            return_value=Mock(results=[[7, first_seen]]),
        ) as mock_query_ai_events:
            result = _count_session_events(Mock(), "s-1", datetime.now(UTC), datetime.now(UTC))

        assert result.event_count == 7
        assert result.first_seen == first_seen
        assert mock_query_ai_events.call_args.kwargs["fall_back_to_events"] is False


class TestFetchSessionForEvaluation:
    def test_queries_in_evaluation_mode_with_both_date_bounds(self):
        with (
            patch("posthog.temporal.ai_observability.run_session_evaluation.Team"),
            patch(
                "posthog.temporal.ai_observability.run_session_evaluation._sum_session_payload_bytes",
                return_value=0,
            ),
            patch(
                "posthog.temporal.ai_observability.run_session_evaluation._count_session_events",
                return_value=_SessionEventCount(event_count=3, first_seen=datetime(2026, 7, 19, tzinfo=UTC)),
            ),
            patch(
                "posthog.temporal.ai_observability.run_session_evaluation.SessionQueryRunner"
            ) as mock_session_query_runner,
        ):
            mock_session_query_runner.return_value.calculate.return_value = Mock(
                results=[_trace("t1", cost=0, latency=0)], hasMore=False
            )
            fetch_session_for_evaluation(1, "s-1", datetime(2026, 7, 20, tzinfo=UTC))

        kwargs = mock_session_query_runner.call_args.kwargs
        assert kwargs["for_evaluation"] is True
        assert kwargs["query"].dateRange.date_from is not None
        assert kwargs["query"].dateRange.date_to is not None
        # SessionQueryRunner defaults to 100 rows under LimitContext.QUERY, which would drop the
        # tail of any session past 100 traces, so the fetch must ask for the export ceiling instead.
        assert kwargs["query"].limit == MAX_SELECT_TRACES_LIMIT_EXPORT

    def test_skips_a_small_session_whose_payload_is_enormous(self):
        """The event count cannot see this: a handful of events carrying megabytes each sits far
        under the row cap while being exactly the payload the cap exists to keep out of the worker.
        """
        with (
            patch("posthog.temporal.ai_observability.run_session_evaluation.Team"),
            patch(
                "posthog.temporal.ai_observability.run_session_evaluation._count_session_events",
                return_value=_SessionEventCount(event_count=14, first_seen=datetime(2026, 7, 19, tzinfo=UTC)),
            ),
            patch(
                "posthog.temporal.ai_observability.run_session_evaluation._sum_session_payload_bytes",
                return_value=payload_budget_bytes(JUDGE_SESSION_MAX_CHARS) + 1,
            ),
            patch(
                "posthog.temporal.ai_observability.run_session_evaluation.SessionQueryRunner"
            ) as mock_session_query_runner,
        ):
            outcome = fetch_session_for_evaluation(1, "s-1", datetime(2026, 7, 20, tzinfo=UTC))

        assert outcome.skip_reason == "session_payload_too_large"
        assert outcome.traces is None
        mock_session_query_runner.assert_not_called()

    def test_widens_date_from_to_the_sessions_real_start(self):
        # A session that had been running for days before window_start must not have its opening
        # cut just because a forward-looking budget (max_age) happened to be shorter than that.
        first_seen = datetime(2026, 7, 10, tzinfo=UTC)
        window_start = datetime(2026, 7, 20, tzinfo=UTC)
        with (
            patch("posthog.temporal.ai_observability.run_session_evaluation.Team"),
            patch(
                "posthog.temporal.ai_observability.run_session_evaluation._sum_session_payload_bytes",
                return_value=0,
            ),
            patch(
                "posthog.temporal.ai_observability.run_session_evaluation._count_session_events",
                return_value=_SessionEventCount(event_count=3, first_seen=first_seen),
            ),
            patch(
                "posthog.temporal.ai_observability.run_session_evaluation.SessionQueryRunner"
            ) as mock_session_query_runner,
        ):
            mock_session_query_runner.return_value.calculate.return_value = Mock(
                results=[_trace("t1", cost=0, latency=0)], hasMore=False
            )
            fetch_session_for_evaluation(1, "s-1", window_start)

        query = mock_session_query_runner.call_args.kwargs["query"]
        assert query.dateRange.date_from == first_seen.isoformat()

    def test_floors_date_from_at_retention_for_a_session_older_than_retention(self):
        # A session's real start is unreachable past ai_events retention regardless of the
        # lookback math, so the fetch must not ask ClickHouse for data it can never return.
        window_start = datetime(2026, 7, 20, tzinfo=UTC)
        first_seen = window_start - timedelta(days=AI_EVENTS_RETENTION_DAYS + 10)
        retention_floor = window_start - timedelta(days=AI_EVENTS_RETENTION_DAYS)
        with (
            patch("posthog.temporal.ai_observability.run_session_evaluation.Team"),
            patch(
                "posthog.temporal.ai_observability.run_session_evaluation._sum_session_payload_bytes",
                return_value=0,
            ),
            patch(
                "posthog.temporal.ai_observability.run_session_evaluation._count_session_events",
                return_value=_SessionEventCount(event_count=3, first_seen=first_seen),
            ),
            patch(
                "posthog.temporal.ai_observability.run_session_evaluation.SessionQueryRunner"
            ) as mock_session_query_runner,
        ):
            mock_session_query_runner.return_value.calculate.return_value = Mock(
                results=[_trace("t1", cost=0, latency=0)], hasMore=False
            )
            fetch_session_for_evaluation(1, "s-1", window_start)

        query = mock_session_query_runner.call_args.kwargs["query"]
        assert query.dateRange.date_from == retention_floor.isoformat()

    def test_returns_traces_oldest_first_even_though_the_runner_orders_newest_first(self):
        # SessionQueryRunner orders `first_timestamp DESC` for the UI session list. The judge's
        # system prompt claims the traces it's handed are "in order", so the fetch must reverse
        # that ordering rather than passing the DESC rows straight through.
        oldest = _trace("t-oldest", cost=0, latency=0, created_at=datetime(2026, 7, 20, 9, tzinfo=UTC))
        middle = _trace("t-middle", cost=0, latency=0, created_at=datetime(2026, 7, 20, 10, tzinfo=UTC))
        newest = _trace("t-newest", cost=0, latency=0, created_at=datetime(2026, 7, 20, 11, tzinfo=UTC))
        with (
            patch("posthog.temporal.ai_observability.run_session_evaluation.Team"),
            patch(
                "posthog.temporal.ai_observability.run_session_evaluation._sum_session_payload_bytes",
                return_value=0,
            ),
            patch(
                "posthog.temporal.ai_observability.run_session_evaluation._count_session_events",
                return_value=_SessionEventCount(event_count=3, first_seen=datetime(2026, 7, 19, tzinfo=UTC)),
            ),
            patch(
                "posthog.temporal.ai_observability.run_session_evaluation.SessionQueryRunner"
            ) as mock_session_query_runner,
        ):
            mock_session_query_runner.return_value.calculate.return_value = Mock(
                results=[newest, middle, oldest], hasMore=False
            )
            outcome = fetch_session_for_evaluation(1, "s-1", datetime(2026, 7, 20, tzinfo=UTC))

        assert outcome.traces is not None
        assert [trace.id for trace in outcome.traces] == ["t-oldest", "t-middle", "t-newest"]

    def test_treats_a_truncated_result_as_a_skip_rather_than_a_partial_grade(self):
        with (
            patch("posthog.temporal.ai_observability.run_session_evaluation.Team"),
            patch(
                "posthog.temporal.ai_observability.run_session_evaluation._sum_session_payload_bytes",
                return_value=0,
            ),
            patch(
                "posthog.temporal.ai_observability.run_session_evaluation._count_session_events",
                return_value=_SessionEventCount(event_count=3, first_seen=datetime(2026, 7, 19, tzinfo=UTC)),
            ),
            patch(
                "posthog.temporal.ai_observability.run_session_evaluation.SessionQueryRunner"
            ) as mock_session_query_runner,
        ):
            mock_session_query_runner.return_value.calculate.return_value = Mock(
                results=[_trace("t1", cost=0, latency=0)], hasMore=True
            )
            outcome = fetch_session_for_evaluation(1, "s-1", datetime(2026, 7, 20, tzinfo=UTC))

        assert outcome.traces is None
        assert outcome.skip_reason == "session_truncated"


@freeze_time(FROZEN_NOW)
class TestExecuteSessionActivities:
    @pytest.mark.parametrize(
        "skip_reason",
        ["session_not_found", "session_too_large", "session_payload_too_large", "session_truncated"],
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
                )
            )

    def test_judge_skips_without_judging_when_the_session_is_truncated(self):
        with (
            patch(
                "posthog.temporal.ai_observability.run_session_evaluation.fetch_session_for_evaluation",
                return_value=SessionFetchOutcome(traces=None, skip_reason="session_truncated", event_count=0),
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
                )
            )
        assert result["skipped"] is True
        assert result["skip_reason"] == "session_truncated"
        # The whole point of the truncation-as-skip choice: never grade a partial transcript.
        mock_call_llm_judge.assert_not_called()

    def test_judge_skips_without_judging_when_the_rendered_transcript_would_overflow(self):
        # The fetch itself succeeds (session_truncated wasn't raised there), but the session has
        # enough traces that format_session_for_judge's char budget can't fit all of them. This is
        # the overflow path the fetch-side truncation check above can't catch.
        traces = [_trace(f"t{i}", cost=0, latency=0, event_count=100) for i in range(260)]
        with (
            patch(
                "posthog.temporal.ai_observability.run_session_evaluation.fetch_session_for_evaluation",
                return_value=SessionFetchOutcome(traces=traces, skip_reason=None, event_count=len(traces)),
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
                )
            )
        assert result["skipped"] is True
        assert result["skip_reason"] == "session_too_long_to_judge"
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
                    )
                )
