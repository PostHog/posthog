import uuid
import asyncio
import dataclasses
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from django.conf import settings
from django.test import override_settings

import temporalio
from asgiref.sync import async_to_sync
from temporalio.client import WorkflowFailureError
from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import ActivityError, ApplicationError, CancelledError, WorkflowAlreadyStartedError
from temporalio.testing import ActivityEnvironment, WorkflowEnvironment
from temporalio.worker import Replayer, UnsandboxedWorkflowRunner, Worker
from temporalio.workflow import ParentClosePolicy

from posthog.models import Organization, Team
from posthog.temporal.ai_observability.evaluation_backfill import (
    ACTIVITY_RETRY_POLICY,
    BACKFILL_MAX_CONSECUTIVE_FAILURES,
    BACKFILL_MAX_IN_FLIGHT,
    MAX_BACKFILL_BATCH_SIZE,
    AdvanceCursorInputs,
    AdvanceCursorOutput,
    CandidatePayload,
    ChildOutcome,
    EvaluationBackfillInputs,
    EvaluationBackfillWorkflow,
    FindCandidatesInputs,
    FindCandidatesOutput,
    MeasureRemainderInputs,
    PrepareTickOutput,
    TickAction,
    _child_outcome,
    advance_evaluation_backfill_cursor_activity,
    child_workflow_name_and_id,
    existing_backfill_child_outcome_activity,
    fail_evaluation_backfill_activity,
    find_evaluation_backfill_candidates_activity,
    measure_evaluation_backfill_remainder_activity,
    prepare_evaluation_backfill_tick_activity,
)
from posthog.temporal.ai_observability.evaluation_llm_judge import _is_last_judge_attempt
from posthog.temporal.ai_observability.evaluation_types import EvaluationActivityResult
from posthog.temporal.ai_observability.evaluation_workflow_activities import (
    LocalEvaluationOutcome,
    RunEvaluationInputs,
    RunLocalEvaluationInputs,
    backfill_verdict_timestamp,
)
from posthog.temporal.ai_observability.run_aggregate_evaluation import (
    RunAggregateEvaluationInputs,
    RunAggregateEvaluationWorkflow,
)
from posthog.temporal.ai_observability.run_evaluation import RunEvaluationWorkflow, WorkflowResult

from products.ai_observability.backend.backfill_candidates import BackfillCandidate, BackfillScope, CandidatePage
from products.ai_observability.backend.models.evaluation_backfill import EvaluationBackfill, EvaluationBackfillStatus
from products.ai_observability.backend.models.evaluations import Evaluation

WINDOW_START = datetime(2026, 1, 1, tzinfo=UTC)
WINDOW_END = datetime(2026, 2, 1, tzinfo=UTC)
UNIT_TIMESTAMP = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)
BACKFILL_MODULE = "posthog.temporal.ai_observability.evaluation_backfill"


class _BackfillMocks:
    def __init__(
        self,
        *,
        activity_results: dict | None = None,
        child_errors_for_ids: dict[str, Exception] | None = None,
        child_results_for_ids: dict[str, WorkflowResult | Exception] | None = None,
    ) -> None:
        self.activity_results = activity_results or {}
        self.child_errors_for_ids = child_errors_for_ids or {}
        self.child_results_for_ids = child_results_for_ids or {}
        self.active_children = 0
        self.peak_children = 0
        self.active_at_advance: list[int] = []
        self.activity_calls: list[tuple] = []
        self.child_calls: list[dict] = []

    async def execute_activity(self, activity_fn, activity_input, **_) -> object:
        self.activity_calls.append((activity_fn, activity_input))
        result = self.activity_results.get(activity_fn)
        if isinstance(result, Exception):
            raise result
        if activity_fn is advance_evaluation_backfill_cursor_activity and activity_fn not in self.activity_results:
            self.active_at_advance.append(self.active_children)
            return AdvanceCursorOutput(finished=activity_input.exhausted)
        return result

    async def start_child_workflow(self, *args, **kwargs) -> object:
        wid = str(kwargs["id"])
        self.child_calls.append(
            {"name": args[0], "id": wid, "inputs": args[1] if len(args) > 1 else None, "kwargs": kwargs}
        )
        if (
            wid is not None
            and wid in self.child_errors_for_ids
            and kwargs.get("id_reuse_policy") != WorkflowIDReusePolicy.ALLOW_DUPLICATE
        ):
            raise self.child_errors_for_ids[wid]

        async def complete() -> WorkflowResult:
            self.active_children += 1
            self.peak_children = max(self.peak_children, self.active_children)
            await asyncio.sleep(0)
            self.active_children -= 1
            default_result: WorkflowResult = {"evaluation_id": "E", "evaluation_type": "hog", "skipped": False}
            result = self.child_results_for_ids.get(wid, default_result)
            if isinstance(result, Exception):
                raise result
            return result

        return asyncio.create_task(complete())


def _inputs() -> EvaluationBackfillInputs:
    return EvaluationBackfillInputs(backfill_id="B", team_id=42)


def _candidate(unit_id: str) -> CandidatePayload:
    return CandidatePayload(
        unit_id=unit_id,
        unit_timestamp=UNIT_TIMESTAMP.isoformat(),
        distinct_id=f"distinct-{unit_id}",
        session_id=f"web-{unit_id}",
        trace_id=f"trace-{unit_id}",
    )


def _tick(**overrides: Any) -> PrepareTickOutput:
    return PrepareTickOutput(action=TickAction.DISPATCH, evaluation_id="E", batch_size=100, **overrides)


def _found(candidates: list[CandidatePayload], *, exhausted: bool = False) -> FindCandidatesOutput:
    return FindCandidatesOutput(
        candidates=candidates,
        next_cursor_timestamp=UNIT_TIMESTAMP.isoformat(),
        next_cursor_unit_id=candidates[-1].unit_id if candidates else "",
        exhausted=exhausted,
        started_from_cursor_timestamp=None,
        started_from_cursor_unit_id="",
    )


async def _run(mocks: _BackfillMocks, inputs: EvaluationBackfillInputs | None = None, *, bounded: bool = False):
    # `workflow.logger` reaches into the workflow runtime, which isn't set up here.
    noop = staticmethod(lambda *_a, **_kw: None)
    fake_logger = type("Logger", (), {"exception": noop, "warning": noop})()
    with (
        patch("temporalio.workflow.logger", fake_logger),
        patch("temporalio.workflow.execute_activity", side_effect=mocks.execute_activity),
        patch("temporalio.workflow.start_child_workflow", side_effect=mocks.start_child_workflow),
        patch("temporalio.workflow.continue_as_new") as continue_as_new,
        patch("temporalio.workflow.sleep", new=AsyncMock()),
        patch("temporalio.workflow.patched", return_value=bounded),
    ):
        await EvaluationBackfillWorkflow().run(inputs or _inputs())
    return continue_as_new


def _called(mocks: _BackfillMocks) -> list:
    return [fn for fn, _ in mocks.activity_calls]


def _advance_input(mocks: _BackfillMocks) -> AdvanceCursorInputs:
    return next(call for fn, call in mocks.activity_calls if fn is advance_evaluation_backfill_cursor_activity)


class TestEvaluationBackfillWorkflow:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("target", ["generation", "trace", "session"])
    @pytest.mark.parametrize(
        "is_backfill,legacy,persistent",
        [(False, False, False), (True, False, False), (True, True, False), (True, False, True)],
    )
    @pytest.mark.parametrize("failure_kind", ["capacity", "dns"])
    async def test_transient_judge_failures_recover_for_backfills(
        self,
        target: str,
        is_backfill: bool,
        legacy: bool,
        persistent: bool,
        failure_kind: str,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        caplog.set_level("INFO", logger="temporalio.workflow")
        caplog.set_level("INFO", logger="temporalio.activity")
        attempts: list[int] = []
        emitted: list[dict[str, Any]] = []
        recovers = is_backfill and not legacy
        evaluation = {
            "id": "E",
            "team_id": 42,
            "evaluation_type": "llm_judge",
            "output_type": "boolean",
            "enabled": True,
            "deleted": False,
        }

        @temporalio.activity.defn(name="run_local_evaluation_activity")
        async def local(_: RunLocalEvaluationInputs) -> LocalEvaluationOutcome:
            return LocalEvaluationOutcome(evaluation=evaluation, result=None, emitted=False)

        @temporalio.activity.defn(name="fetch_evaluation_activity")
        async def fetch(_: RunEvaluationInputs) -> dict[str, Any]:
            return evaluation

        @temporalio.activity.defn(
            name={
                "generation": "execute_llm_judge_activity",
                "trace": "execute_trace_llm_judge_activity",
                "session": "execute_session_llm_judge_activity",
            }[target]
        )
        async def judge(payload: dict[str, Any]) -> EvaluationActivityResult:
            info = temporalio.activity.info()
            attempt = info.attempt
            if recovers:
                assert info.schedule_to_close_timeout == timedelta(minutes=30)
            attempts.append(attempt)
            if attempt <= 4 or persistent:
                if failure_kind == "dns" and _is_last_judge_attempt(payload.get("retry_maximum_attempts")):
                    return {
                        "result_type": "boolean",
                        "skipped": True,
                        "skip_reason": "host_unresolved",
                        "reasoning": "Example endpoint could not resolve",
                        "allows_na": False,
                    }
                raise ApplicationError("Query capacity is temporarily unavailable", type="ConcurrencyLimitExceeded")
            return {"result_type": "boolean", "verdict": True, "reasoning": "ok", "allows_na": False}

        @temporalio.activity.defn(
            name="emit_evaluation_event_activity" if target == "generation" else "emit_trace_evaluation_event_activity"
        )
        async def emit(payload: dict[str, Any]) -> None:
            emitted.append(payload)

        @temporalio.activity.defn(name="emit_internal_telemetry_activity")
        async def telemetry(_: dict[str, Any]) -> None:
            return

        inputs: RunEvaluationInputs | RunAggregateEvaluationInputs
        backfill_id = "B" if is_backfill else None
        if target == "generation":
            inputs = RunEvaluationInputs(evaluation_id="E", event_data={"team_id": 42}, backfill_id=backfill_id)
            workflow_name = "run-evaluation"
        else:
            inputs = RunAggregateEvaluationInputs(
                evaluation_id="E",
                team_id=42,
                trace_id="example-trace",
                distinct_id="example-user",
                ai_session_id="example-session" if target == "session" else None,
                target=target,
                settle={"strategy": "fixed_window", "window_seconds": 10},
                anchor_timestamp=UNIT_TIMESTAMP.isoformat() if is_backfill else None,
                backfill_id=backfill_id,
            )
            workflow_name = "run-aggregate-evaluation"

        task_queue = str(uuid.uuid4())
        original_patched = temporalio.workflow.patched

        def patched(patch_id: str) -> bool:
            if legacy and patch_id == "evaluation-backfill-extended-retries":
                return False
            return original_patched(patch_id)

        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with Worker(
                env.client,
                task_queue=task_queue,
                workflows=[RunEvaluationWorkflow, RunAggregateEvaluationWorkflow],
                activities=[local, fetch, judge, emit, telemetry],
                workflow_runner=UnsandboxedWorkflowRunner(),
            ):
                with patch("temporalio.workflow.patched", side_effect=patched):
                    handle = await env.client.start_workflow(
                        workflow_name,
                        inputs,
                        id=str(uuid.uuid4()),
                        task_queue=task_queue,
                        execution_timeout=timedelta(minutes=40),
                    )
                    if persistent or (not recovers and failure_kind == "capacity"):
                        with pytest.raises(WorkflowFailureError):
                            await handle.result()
                    elif recovers:
                        result = await handle.result()
                        assert result["verdict"] is True
                    else:
                        result = await handle.result()
                        assert result["skip_reason"] == "host_unresolved"
                    history = await handle.fetch_history()

        if persistent:
            assert len(attempts) > 4
            assert emitted == []
        else:
            assert attempts == ([1, 2, 3, 4, 5] if recovers else [1, 2, 3])
            assert len(emitted) == int(recovers or failure_kind == "dns")
        await Replayer(
            workflows=[RunEvaluationWorkflow, RunAggregateEvaluationWorkflow],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ).replay_workflow(history)

    @pytest.mark.parametrize(
        "reason,outcome",
        [
            ("parse_error", ChildOutcome.RETRYABLE),
            ("unparsable_response", ChildOutcome.RETRYABLE),
            ("output_limit_exceeded", ChildOutcome.RETRYABLE),
            ("host_unresolved", ChildOutcome.RETRYABLE),
            ("content_filtered", ChildOutcome.SKIPPED),
            ("request_rejected", ChildOutcome.SKIPPED),
        ],
    )
    def test_unusable_responses_are_retryable_but_terminal_skips_are_preserved(
        self, reason: str, outcome: ChildOutcome
    ) -> None:
        assert (
            _child_outcome(
                {"evaluation_id": "E", "evaluation_type": "llm_judge", "skipped": True, "skip_reason": reason}
            )
            == outcome
        )

    @pytest.mark.asyncio
    async def test_bounded_dispatch_waits_for_outcomes_before_advancing(self) -> None:
        found = dataclasses.replace(
            _found([_candidate(f"u{i}") for i in range(19)], exhausted=True),
            next_cursor_timestamp=(UNIT_TIMESTAMP - timedelta(hours=1)).isoformat(),
            next_cursor_unit_id="filtered-out-unit",
        )
        mocks = _BackfillMocks(
            activity_results={
                prepare_evaluation_backfill_tick_activity: _tick(),
                find_evaluation_backfill_candidates_activity: found,
            }
        )

        await _run(mocks, bounded=True)

        advances = [value for fn, value in mocks.activity_calls if fn is advance_evaluation_backfill_cursor_activity]
        assert mocks.peak_children == BACKFILL_MAX_IN_FLIGHT
        assert mocks.active_at_advance == [0] * len(advances)
        assert sum(value.completed_delta for value in advances) == 19
        assert [value.exhausted for value in advances] == [False, False, False, False, True]
        assert advances[1].expected_cursor_unit_id == advances[0].new_cursor_unit_id
        assert (advances[-1].new_cursor_timestamp, advances[-1].new_cursor_unit_id) == (
            found.next_cursor_timestamp,
            found.next_cursor_unit_id,
        )

    @pytest.mark.asyncio
    async def test_bounded_dispatch_records_execution_failures_and_skips(self) -> None:
        mocks = _BackfillMocks(
            activity_results={
                prepare_evaluation_backfill_tick_activity: _tick(),
                find_evaluation_backfill_candidates_activity: _found(
                    [_candidate(f"u{i}") for i in range(4)], exhausted=True
                ),
            },
            child_results_for_ids={
                "llma-hog-eval-E-u1-ingestion": RuntimeError("worker unavailable"),
                "llma-hog-eval-E-u2-ingestion": {
                    "evaluation_id": "E",
                    "evaluation_type": "hog",
                    "skipped": True,
                    "skip_reason": "request_rejected",
                },
                "llma-hog-eval-E-u3-ingestion": {
                    "evaluation_id": "E",
                    "evaluation_type": "hog",
                    "skipped": True,
                    "skip_reason": "key_invalid",
                },
            },
        )

        await _run(mocks, bounded=True)

        result = _advance_input(mocks)
        assert (
            result.dispatched_delta,
            result.completed_delta,
            result.evaluation_skipped_delta,
            result.failed_delta,
        ) == (4, 1, 1, 2)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "outcome,restarted",
        [(ChildOutcome.EVALUATED, False), (ChildOutcome.SKIPPED, False), (ChildOutcome.RETRYABLE, True)],
    )
    async def test_only_unfinished_existing_evaluations_are_restarted(
        self, outcome: ChildOutcome, restarted: bool
    ) -> None:
        workflow_id = "llma-hog-eval-E-u1-ingestion"
        mocks = _BackfillMocks(
            activity_results={
                prepare_evaluation_backfill_tick_activity: _tick(),
                find_evaluation_backfill_candidates_activity: _found([_candidate("u1")], exhausted=True),
                existing_backfill_child_outcome_activity: outcome,
            },
            child_errors_for_ids={workflow_id: WorkflowAlreadyStartedError(workflow_id, "run-evaluation")},
        )

        await _run(mocks, bounded=True)

        assert len(mocks.child_calls) == (2 if restarted else 1)
        assert _advance_input(mocks).completed_delta == int(restarted)
        assert _advance_input(mocks).skipped_delta == int(not restarted)

    @pytest.mark.asyncio
    async def test_failed_group_stops_before_dispatching_more(self) -> None:
        mocks = _BackfillMocks(
            activity_results={
                prepare_evaluation_backfill_tick_activity: _tick(),
                find_evaluation_backfill_candidates_activity: _found([_candidate(f"u{i}") for i in range(9)]),
            },
            child_results_for_ids={
                f"llma-hog-eval-E-u{i}-ingestion": RuntimeError("worker unavailable") for i in range(4)
            },
        )

        await _run(mocks, bounded=True)

        assert len(mocks.child_calls) == 4
        assert fail_evaluation_backfill_activity in _called(mocks)

    @pytest.mark.asyncio
    async def test_finished_tick_returns_without_dispatch(self) -> None:
        mocks = _BackfillMocks(
            activity_results={prepare_evaluation_backfill_tick_activity: PrepareTickOutput(action=TickAction.FINISHED)}
        )

        continue_as_new = await _run(mocks)

        assert _called(mocks) == [prepare_evaluation_backfill_tick_activity]
        assert mocks.child_calls == []
        continue_as_new.assert_not_called()

    @pytest.mark.asyncio
    async def test_dispatch_starts_one_child_per_candidate_and_advances_cursor(self) -> None:
        candidates = [_candidate("u1"), _candidate("u2"), _candidate("u3")]
        mocks = _BackfillMocks(
            activity_results={
                prepare_evaluation_backfill_tick_activity: _tick(),
                find_evaluation_backfill_candidates_activity: _found(candidates),
            }
        )

        continue_as_new = await _run(mocks)

        assert [call["id"] for call in mocks.child_calls] == [
            "llma-hog-eval-E-u1-ingestion",
            "llma-hog-eval-E-u2-ingestion",
            "llma-hog-eval-E-u3-ingestion",
        ]
        # ABANDON is load-bearing: the default policy terminates every child at continue_as_new.
        kwargs = mocks.child_calls[0]["kwargs"]
        assert kwargs["parent_close_policy"] == ParentClosePolicy.ABANDON
        assert kwargs["id_reuse_policy"] == WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY
        assert kwargs["task_queue"] == settings.LLMA_EVALS_TASK_QUEUE
        advance = _advance_input(mocks)
        assert (advance.dispatched_delta, advance.skipped_delta) == (3, 0)
        assert (advance.expected_cursor_timestamp, advance.expected_cursor_unit_id) == (None, "")
        assert (advance.new_cursor_timestamp, advance.new_cursor_unit_id) == (UNIT_TIMESTAMP.isoformat(), "u3")
        assert not advance.exhausted
        continue_as_new.assert_called_once()

    @pytest.mark.asyncio
    async def test_existing_child_counts_as_skipped(self) -> None:
        mocks = _BackfillMocks(
            activity_results={
                prepare_evaluation_backfill_tick_activity: _tick(),
                find_evaluation_backfill_candidates_activity: _found(
                    [_candidate("u1"), _candidate("u2"), _candidate("u3")]
                ),
            },
            child_errors_for_ids={
                "llma-hog-eval-E-u2-ingestion": WorkflowAlreadyStartedError("llma-hog-eval-E-u2-ingestion", "x")
            },
        )

        await _run(mocks)

        advance = _advance_input(mocks)
        assert (advance.dispatched_delta, advance.skipped_delta) == (2, 1)

    @pytest.mark.asyncio
    async def test_a_start_failure_counts_as_failed(self) -> None:
        mocks = _BackfillMocks(
            activity_results={
                prepare_evaluation_backfill_tick_activity: _tick(),
                find_evaluation_backfill_candidates_activity: _found(
                    [_candidate("u1"), _candidate("u2"), _candidate("u3")]
                ),
            },
            child_errors_for_ids={"llma-hog-eval-E-u2-ingestion": RuntimeError("temporal refused the start")},
        )

        await _run(mocks)

        advance = _advance_input(mocks)
        assert (advance.dispatched_delta, advance.skipped_delta, advance.failed_delta) == (2, 0, 1)

    @pytest.mark.asyncio
    async def test_exhausted_page_finishes_without_continue_as_new(self) -> None:
        mocks = _BackfillMocks(
            activity_results={
                prepare_evaluation_backfill_tick_activity: _tick(),
                find_evaluation_backfill_candidates_activity: _found([_candidate("u1")], exhausted=True),
                advance_evaluation_backfill_cursor_activity: AdvanceCursorOutput(finished=True),
            }
        )

        continue_as_new = await _run(mocks)

        assert _advance_input(mocks).exhausted
        called = _called(mocks)
        assert called.index(measure_evaluation_backfill_remainder_activity) > called.index(
            advance_evaluation_backfill_cursor_activity
        )
        continue_as_new.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "failing_activity",
        [prepare_evaluation_backfill_tick_activity, find_evaluation_backfill_candidates_activity],
    )
    async def test_failing_tick_continues_as_new_with_an_incremented_failure_count(self, failing_activity) -> None:
        mocks = _BackfillMocks(
            activity_results={
                prepare_evaluation_backfill_tick_activity: _tick(),
                find_evaluation_backfill_candidates_activity: _found([_candidate("u1")]),
                failing_activity: RuntimeError("postgres is down"),
            }
        )

        continue_as_new = await _run(mocks, EvaluationBackfillInputs(backfill_id="B", team_id=42))

        assert fail_evaluation_backfill_activity not in _called(mocks)
        continue_as_new.assert_called_once_with(
            EvaluationBackfillInputs(backfill_id="B", team_id=42, consecutive_failures=1)
        )

    @pytest.mark.asyncio
    async def test_a_cancelled_activity_ends_the_run_instead_of_counting_as_a_failure(self) -> None:
        # Cancelling a backfill cancels its in-flight activity, which must not read as a tick
        # that failed: the run would log an error and spend one of its five failures.
        mocks = _BackfillMocks(
            activity_results={
                prepare_evaluation_backfill_tick_activity: _tick(),
                find_evaluation_backfill_candidates_activity: ActivityError(
                    "activity cancelled",
                    scheduled_event_id=1,
                    started_event_id=2,
                    identity="test",
                    activity_type="find",
                    activity_id="1",
                    retry_state=None,
                ),
            }
        )
        cause = CancelledError("cancelled")
        cast(ActivityError, mocks.activity_results[find_evaluation_backfill_candidates_activity]).__cause__ = cause

        with pytest.raises(ActivityError):
            await _run(mocks)

        assert fail_evaluation_backfill_activity not in _called(mocks)

    @pytest.mark.asyncio
    async def test_repeated_failures_cancel_the_backfill_instead_of_looping_forever(self) -> None:
        mocks = _BackfillMocks(
            activity_results={
                prepare_evaluation_backfill_tick_activity: _tick(),
                find_evaluation_backfill_candidates_activity: RuntimeError("clickhouse is down"),
            }
        )
        inputs = EvaluationBackfillInputs(
            backfill_id="B", team_id=42, consecutive_failures=BACKFILL_MAX_CONSECUTIVE_FAILURES - 1
        )

        continue_as_new = await _run(mocks, inputs)

        assert _called(mocks)[-1] is fail_evaluation_backfill_activity
        continue_as_new.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "target,expected",
        [
            (
                "generation",
                RunEvaluationInputs(
                    evaluation_id="E",
                    event_data={
                        "uuid": "u1",
                        "team_id": 42,
                        "timestamp": UNIT_TIMESTAMP.isoformat(),
                        "trace_id": "trace-u1",
                    },
                    backfill_id="B",
                ),
            ),
            (
                "trace",
                RunAggregateEvaluationInputs(
                    evaluation_id="E",
                    team_id=42,
                    trace_id="u1",
                    distinct_id="distinct-u1",
                    session_id="web-u1",
                    ai_session_id=None,
                    target="trace",
                    settle={"window_seconds": 30},
                    anchor_timestamp=UNIT_TIMESTAMP.isoformat(),
                    backfill_id="B",
                ),
            ),
            (
                "session",
                RunAggregateEvaluationInputs(
                    evaluation_id="E",
                    team_id=42,
                    trace_id="",
                    distinct_id="distinct-u1",
                    session_id="web-u1",
                    ai_session_id="u1",
                    target="session",
                    settle={"window_seconds": 30},
                    anchor_timestamp=UNIT_TIMESTAMP.isoformat(),
                    backfill_id="B",
                ),
            ),
        ],
    )
    async def test_child_inputs_carry_the_unit_in_the_field_its_target_reads(self, target, expected) -> None:
        mocks = _BackfillMocks(
            activity_results={
                prepare_evaluation_backfill_tick_activity: _tick(target=target, settle={"window_seconds": 30}),
                find_evaluation_backfill_candidates_activity: _found([_candidate("u1")]),
            }
        )

        await _run(mocks)

        assert mocks.child_calls[0]["inputs"] == expected


@pytest.mark.parametrize(
    "target,evaluation_type,rerun_existing,unit_id,expected_name,expected_id",
    [
        ("generation", "hog", False, "U", "run-evaluation", "llma-hog-eval-E-U-ingestion"),
        ("generation", "llm_judge", True, "U", "run-evaluation", "llma-llm-eval-E-U-backfill-B"),
        ("trace", "hog", False, "U", "run-aggregate-evaluation", "llma-trace-eval-E-U"),
        ("session", "hog", False, "U", "run-aggregate-evaluation", "llma-session-eval-E-U"),
        ("trace", "hog", True, "U", "run-aggregate-evaluation", "llma-trace-eval-E-U-backfill-B"),
        # 32 hex characters is the md5 the Node scheduler falls back to past 128 characters;
        # without the same fallback a backfill child would not collide with the live path's id.
        (
            "trace",
            "hog",
            False,
            "t" * 129,
            "run-aggregate-evaluation",
            "llma-trace-eval-E-4670e99bfd94a7cdfa2de20b9a018676",
        ),
    ],
)
def test_child_workflow_ids_match_live_scheduler_unless_rerun(
    target, evaluation_type, rerun_existing, unit_id, expected_name, expected_id
) -> None:
    child = child_workflow_name_and_id(
        evaluation_id="E",
        evaluation_type=evaluation_type,
        target=target,
        unit_id=unit_id,
        backfill_id="B",
        rerun_existing=rerun_existing,
    )

    assert (child.name, child.workflow_id) == (expected_name, expected_id)


def test_backfill_verdict_timestamps_are_stable_and_stay_inside_the_unit_second() -> None:
    first = backfill_verdict_timestamp(UNIT_TIMESTAMP, "E", "bf-1", "u1")

    assert first == backfill_verdict_timestamp(UNIT_TIMESTAMP, "E", "bf-1", "u1")
    # Each of the three ids has to move the offset, or verdicts that differ only in that id keep
    # sharing an ingestion dedup key and all but one are dropped.
    assert first != backfill_verdict_timestamp(UNIT_TIMESTAMP, "E", "bf-2", "u1")
    assert first != backfill_verdict_timestamp(UNIT_TIMESTAMP, "E2", "bf-1", "u1")
    assert first != backfill_verdict_timestamp(UNIT_TIMESTAMP, "E", "bf-1", "u2")
    # Ingestion keeps millisecond precision, so the spread is about 1000 usable buckets.
    for unit_id in ("u1", "u2", "u3"):
        offset = backfill_verdict_timestamp(UNIT_TIMESTAMP, "E", "bf-1", unit_id) - UNIT_TIMESTAMP
        assert timedelta(0) <= offset < timedelta(seconds=1)


@pytest.fixture
def backfill_data():
    organization = Organization.objects.create(name="Org")
    team = Team.objects.create(organization=organization, name="Team")
    evaluation = Evaluation.objects.create(
        team=team,
        name="e",
        evaluation_type="hog",
        evaluation_config={"source": "return true"},
        output_type="boolean",
        output_config={},
        conditions=[],
        target="generation",
        enabled=True,
    )
    backfill = EvaluationBackfill.objects.for_team(team.id).create(
        team=team,
        evaluation=evaluation,
        window_start=WINDOW_START,
        window_end=WINDOW_END,
        target="generation",
        conditions=[],
        total_count=10,
    )
    return {"team": team, "evaluation": evaluation, "backfill": backfill}


def _update_backfill(backfill_data, **fields) -> None:
    EvaluationBackfill.objects.for_team(backfill_data["team"].id).filter(pk=backfill_data["backfill"].id).update(
        **fields
    )


def _finished_events(capture: MagicMock) -> list[dict]:
    return [
        call.kwargs["properties"]
        for call in capture.return_value.call_args_list
        if call.kwargs["event"] == "llma evaluation backfill finished"
    ]


def _measure_inputs(backfill_data) -> MeasureRemainderInputs:
    return MeasureRemainderInputs(backfill_id=str(backfill_data["backfill"].id), team_id=backfill_data["team"].id)


def _activity_inputs(backfill_data) -> EvaluationBackfillInputs:
    return EvaluationBackfillInputs(backfill_id=str(backfill_data["backfill"].id), team_id=backfill_data["team"].id)


def _advance(
    backfill_data,
    *,
    dispatched_delta: int = 1,
    skipped_delta: int = 0,
    failed_delta: int = 0,
    completed_delta: int | None = None,
    evaluation_skipped_delta: int = 0,
    exhausted: bool = False,
) -> AdvanceCursorInputs:
    return AdvanceCursorInputs(
        backfill_id=str(backfill_data["backfill"].id),
        team_id=backfill_data["team"].id,
        expected_cursor_timestamp=None,
        expected_cursor_unit_id="",
        new_cursor_timestamp=UNIT_TIMESTAMP.isoformat(),
        new_cursor_unit_id="u3",
        dispatched_delta=dispatched_delta,
        skipped_delta=skipped_delta,
        failed_delta=failed_delta,
        completed_delta=completed_delta,
        evaluation_skipped_delta=evaluation_skipped_delta,
        exhausted=exhausted,
    )


@pytest.mark.django_db(transaction=True)
class TestEvaluationBackfillActivities:
    @pytest.mark.parametrize(
        "dispatched,skipped,failed,rerun,counted,expected",
        [
            (1, 15, 0, False, 14, 0),
            (3000, 0, 0, False, 3000, 0),
            (1, 0, 0, False, 5, 4),
            (0, 3, 1, False, 1, 1),
            (0, 3, 1, False, 0, 0),
            (0, 3, 1, True, 1, 0),
        ],
    )
    def test_remainder_discounts_every_unit_the_run_covered(
        self,
        backfill_data,
        dispatched: int,
        skipped: int,
        failed: int,
        rerun: bool,
        counted: int,
        expected: int,
    ) -> None:
        _update_backfill(
            backfill_data,
            dispatched_count=dispatched,
            skipped_count=skipped,
            failed_count=failed,
            rerun_existing=rerun,
        )

        with patch(
            "posthog.temporal.ai_observability.evaluation_backfill.count_backfill_candidates",
            return_value=BackfillScope(to_evaluate=counted, already_judged=0),
        ):
            async_to_sync(measure_evaluation_backfill_remainder_activity)(
                MeasureRemainderInputs(backfill_id=str(backfill_data["backfill"].id), team_id=backfill_data["team"].id)
            )

        backfill_data["backfill"].refresh_from_db()
        assert backfill_data["backfill"].remaining_count == expected

    @pytest.mark.parametrize(
        "status,reported",
        [(EvaluationBackfillStatus.COMPLETED, True), (EvaluationBackfillStatus.CANCELLED, False)],
    )
    def test_measuring_a_completed_run_reports_it_finished(self, backfill_data, status, reported) -> None:
        _update_backfill(
            backfill_data,
            status=status,
            dispatched_count=6,
            skipped_count=1,
            failed_count=1,
            finished_at=backfill_data["backfill"].created_at + timedelta(minutes=5),
        )

        with (
            patch(
                f"{BACKFILL_MODULE}.count_backfill_candidates",
                return_value=BackfillScope(to_evaluate=3, already_judged=0),
            ),
            patch(f"{BACKFILL_MODULE}.ph_background_capture") as capture,
        ):
            async_to_sync(measure_evaluation_backfill_remainder_activity)(_measure_inputs(backfill_data))

        expected = {
            "backfill_id": str(backfill_data["backfill"].id),
            "evaluation_id": str(backfill_data["evaluation"].id),
            "status": "completed",
            "target": "generation",
            "evaluation_type": "hog",
            "rerun_existing": False,
            "total_count": 10,
            "dispatched_count": 6,
            "skipped_count": 1,
            "failed_count": 1,
            "remaining_count": 1,
            "completed_count": None,
            "evaluation_skipped_count": 0,
            "duration_seconds": 300.0,
            "stop_reason": None,
        }
        assert _finished_events(capture) == ([expected] if reported else [])
        if reported:
            assert capture.return_value.call_args.kwargs["groups"]["project"] == str(backfill_data["team"].uuid)

    @pytest.mark.parametrize("attempt,reported", [(1, False), (ACTIVITY_RETRY_POLICY.maximum_attempts, True)])
    def test_a_count_that_keeps_failing_reports_the_run_without_a_remainder(
        self, backfill_data, attempt, reported
    ) -> None:
        _update_backfill(
            backfill_data,
            status=EvaluationBackfillStatus.COMPLETED,
            finished_at=backfill_data["backfill"].created_at + timedelta(minutes=5),
        )
        env = ActivityEnvironment()
        env.info = dataclasses.replace(env.info, attempt=attempt)

        async def measure() -> None:
            await env.run(measure_evaluation_backfill_remainder_activity, _measure_inputs(backfill_data))

        with (
            patch(f"{BACKFILL_MODULE}.count_backfill_candidates", side_effect=RuntimeError("clickhouse down")),
            patch(f"{BACKFILL_MODULE}.ph_background_capture") as capture,
            pytest.raises(RuntimeError),
        ):
            async_to_sync(measure)()

        events = _finished_events(capture)
        assert [event["remaining_count"] for event in events] == ([None] if reported else [])

    def test_failing_a_backfill_reports_it_once_as_failed(self, backfill_data) -> None:
        with patch(f"{BACKFILL_MODULE}.ph_background_capture") as capture:
            async_to_sync(fail_evaluation_backfill_activity)(_activity_inputs(backfill_data))
            async_to_sync(fail_evaluation_backfill_activity)(_activity_inputs(backfill_data))

        assert [event["status"] for event in _finished_events(capture)] == ["failed"]

    def test_a_failed_capture_still_fails_the_backfill(self, backfill_data) -> None:
        with patch(f"{BACKFILL_MODULE}.ph_background_capture", side_effect=RuntimeError("capture down")):
            async_to_sync(fail_evaluation_backfill_activity)(_activity_inputs(backfill_data))

        backfill_data["backfill"].refresh_from_db()
        assert backfill_data["backfill"].status == EvaluationBackfillStatus.INTERRUPTED

    @pytest.mark.parametrize("status", [EvaluationBackfillStatus.COMPLETED, EvaluationBackfillStatus.CANCELLED, None])
    def test_prepare_returns_finished_for_missing_or_terminal_row(self, backfill_data, status) -> None:
        inputs = _activity_inputs(backfill_data)
        if status is None:
            inputs = EvaluationBackfillInputs(backfill_id=str(uuid.uuid4()), team_id=backfill_data["team"].id)
        else:
            _update_backfill(backfill_data, status=status)

        result = async_to_sync(prepare_evaluation_backfill_tick_activity)(inputs)

        assert result.action == TickAction.FINISHED

    @pytest.mark.parametrize(
        "update,stop_reason",
        [
            ({"deleted": True}, "evaluation_deleted"),
            # No workflow id prefix exists for this type, so no child could ever be started.
            ({"evaluation_type": "not_a_real_type"}, "unsupported_evaluation_type"),
            # Nothing tells the loop a paused evaluation came back, so holding the cursor would
            # leave the row RUNNING and the workflow ticking forever.
            ({"enabled": False}, "evaluation_disabled"),
        ],
    )
    def test_prepare_cancels_the_row_when_the_evaluation_cannot_run(self, backfill_data, update, stop_reason) -> None:
        Evaluation.objects.filter(pk=backfill_data["evaluation"].id).update(**update)

        with patch(f"{BACKFILL_MODULE}.ph_background_capture") as capture:
            result = async_to_sync(prepare_evaluation_backfill_tick_activity)(_activity_inputs(backfill_data))
            async_to_sync(prepare_evaluation_backfill_tick_activity)(_activity_inputs(backfill_data))

        assert result.action == TickAction.FINISHED
        backfill_data["backfill"].refresh_from_db()
        assert backfill_data["backfill"].status == EvaluationBackfillStatus.INTERRUPTED
        assert backfill_data["backfill"].finished_at is not None
        assert [(event["status"], event["stop_reason"]) for event in _finished_events(capture)] == [
            ("stopped", stop_reason)
        ]

    @pytest.mark.parametrize(
        "configured,expected",
        [(7, 7), (0, 1), (-5, 1), (MAX_BACKFILL_BATCH_SIZE * 10, MAX_BACKFILL_BATCH_SIZE)],
    )
    def test_prepare_dispatches_with_a_clamped_batch_size(self, backfill_data, configured, expected) -> None:
        with override_settings(LLMA_EVAL_BACKFILL_BATCH_SIZE=configured):
            result = async_to_sync(prepare_evaluation_backfill_tick_activity)(_activity_inputs(backfill_data))

        assert result == PrepareTickOutput(
            action=TickAction.DISPATCH,
            evaluation_id=str(backfill_data["evaluation"].id),
            target="generation",
            evaluation_type="hog",
            # A generation evaluation carries no settle config; the model normalizes the bag to {}.
            settle={},
            rerun_existing=False,
            batch_size=expected,
        )

    def test_find_serializes_candidates_and_cursor(self, backfill_data) -> None:
        _update_backfill(backfill_data, cursor_timestamp=UNIT_TIMESTAMP + timedelta(hours=1), cursor_unit_id="u0")
        page = CandidatePage(
            candidates=[
                BackfillCandidate(
                    unit_id="u1",
                    unit_timestamp=UNIT_TIMESTAMP,
                    distinct_id="d1",
                    session_id="web-1",
                    trace_id="t1",
                )
            ],
            next_cursor_timestamp=UNIT_TIMESTAMP,
            next_cursor_unit_id="u1",
            exhausted=True,
        )

        with patch(
            "posthog.temporal.ai_observability.evaluation_backfill.fetch_backfill_candidates", return_value=page
        ) as fetch:
            result = async_to_sync(find_evaluation_backfill_candidates_activity)(
                FindCandidatesInputs(
                    backfill_id=str(backfill_data["backfill"].id), team_id=backfill_data["team"].id, limit=5
                )
            )

        assert fetch.call_args.kwargs["cursor_timestamp"] == UNIT_TIMESTAMP + timedelta(hours=1)
        assert fetch.call_args.kwargs["cursor_unit_id"] == "u0"
        assert fetch.call_args.kwargs["limit"] == 5
        assert result.candidates == [
            CandidatePayload(
                unit_id="u1",
                unit_timestamp=UNIT_TIMESTAMP.isoformat(),
                distinct_id="d1",
                session_id="web-1",
                trace_id="t1",
            )
        ]
        assert (result.next_cursor_timestamp, result.next_cursor_unit_id) == (UNIT_TIMESTAMP.isoformat(), "u1")
        assert (result.started_from_cursor_timestamp, result.started_from_cursor_unit_id) == (
            (UNIT_TIMESTAMP + timedelta(hours=1)).isoformat(),
            "u0",
        )
        assert result.exhausted

    def test_advance_is_idempotent_on_retry(self, backfill_data) -> None:
        advance = _advance(
            backfill_data,
            dispatched_delta=5,
            skipped_delta=1,
            failed_delta=2,
            completed_delta=2,
            evaluation_skipped_delta=1,
        )

        first = async_to_sync(advance_evaluation_backfill_cursor_activity)(advance)
        second = async_to_sync(advance_evaluation_backfill_cursor_activity)(advance)

        backfill_data["backfill"].refresh_from_db()
        row = backfill_data["backfill"]
        assert (row.dispatched_count, row.skipped_count, row.failed_count) == (5, 1, 2)
        assert (row.completed_count, row.evaluation_skipped_count) == (2, 1)
        assert backfill_data["backfill"].cursor_unit_id == "u3"
        assert not first.finished
        # The second call matched nothing because the first already moved the cursor. Reading that
        # as finished would end the loop with the row still RUNNING and the window half walked.
        assert not second.finished

    def test_advance_marks_completed_when_exhausted(self, backfill_data) -> None:
        result = async_to_sync(advance_evaluation_backfill_cursor_activity)(_advance(backfill_data, exhausted=True))

        assert result.finished
        backfill_data["backfill"].refresh_from_db()
        assert backfill_data["backfill"].status == EvaluationBackfillStatus.COMPLETED
        assert backfill_data["backfill"].finished_at is not None

    def test_resuming_legacy_backfill_does_not_claim_partial_outcomes_are_totals(self, backfill_data) -> None:
        _update_backfill(backfill_data, dispatched_count=3, cursor_timestamp=UNIT_TIMESTAMP, cursor_unit_id="u0")
        advance = dataclasses.replace(
            _advance(backfill_data, dispatched_delta=2, completed_delta=2, exhausted=True),
            expected_cursor_timestamp=UNIT_TIMESTAMP.isoformat(),
            expected_cursor_unit_id="u0",
        )

        async_to_sync(advance_evaluation_backfill_cursor_activity)(advance)

        row = backfill_data["backfill"]
        row.refresh_from_db()
        assert row.dispatched_count == 5
        assert row.completed_count is None
        assert row.remaining_count is None

    def test_advance_loses_to_concurrent_cancel(self, backfill_data) -> None:
        _update_backfill(backfill_data, status=EvaluationBackfillStatus.CANCELLED)

        result = async_to_sync(advance_evaluation_backfill_cursor_activity)(_advance(backfill_data))

        assert result.finished
        backfill_data["backfill"].refresh_from_db()
        assert backfill_data["backfill"].status == EvaluationBackfillStatus.CANCELLED
        assert backfill_data["backfill"].dispatched_count == 0


@temporalio.workflow.defn(name="run-evaluation")
class BackfillRecoveryTestJudge:
    @temporalio.workflow.run
    async def run(self, inputs: RunEvaluationInputs) -> WorkflowResult:
        skipped = inputs.backfill_id == "original"
        return {
            "evaluation_id": inputs.evaluation_id,
            "evaluation_type": "hog",
            "skipped": skipped,
            "skip_reason": "key_invalid" if skipped else "",
        }


@pytest.mark.asyncio
async def test_temporal_recovers_a_skipped_workflow_and_preserves_the_verdict(caplog) -> None:
    caplog.set_level("INFO", logger="temporalio.workflow")
    caplog.set_level("INFO", logger="temporalio.activity")
    advances: list[AdvanceCursorInputs] = []

    @temporalio.activity.defn(name="prepare_evaluation_backfill_tick_activity")
    async def prepare(inputs: EvaluationBackfillInputs) -> PrepareTickOutput:
        return _tick()

    @temporalio.activity.defn(name="find_evaluation_backfill_candidates_activity")
    async def find(inputs: FindCandidatesInputs) -> FindCandidatesOutput:
        return _found([_candidate("u1")], exhausted=True)

    @temporalio.activity.defn(name="advance_evaluation_backfill_cursor_activity")
    async def advance(inputs: AdvanceCursorInputs) -> AdvanceCursorOutput:
        advances.append(inputs)
        return AdvanceCursorOutput(finished=True)

    @temporalio.activity.defn(name="measure_evaluation_backfill_remainder_activity")
    async def measure(inputs: MeasureRemainderInputs) -> None:
        return None

    task_queue = f"backfill-recovery-{uuid.uuid4()}"
    async with await WorkflowEnvironment.start_time_skipping() as env:
        with (
            override_settings(LLMA_EVALS_TASK_QUEUE=task_queue),
            patch(f"{BACKFILL_MODULE}.async_connect", new=AsyncMock(return_value=env.client)),
        ):
            async with Worker(
                env.client,
                task_queue=task_queue,
                workflows=[EvaluationBackfillWorkflow, BackfillRecoveryTestJudge],
                activities=[prepare, find, advance, measure, existing_backfill_child_outcome_activity],
                workflow_runner=UnsandboxedWorkflowRunner(),
            ):
                await env.client.execute_workflow(
                    BackfillRecoveryTestJudge.run,
                    RunEvaluationInputs(evaluation_id="E", event_data={"team_id": 42}, backfill_id="original"),
                    id="llma-hog-eval-E-u1-ingestion",
                    task_queue=task_queue,
                    execution_timeout=timedelta(seconds=30),
                )
                for _ in range(2):
                    await env.client.execute_workflow(
                        EvaluationBackfillWorkflow.run,
                        _inputs(),
                        id=f"test-backfill-{uuid.uuid4()}",
                        task_queue=task_queue,
                        execution_timeout=timedelta(seconds=60),
                    )
    assert [(item.completed_delta, item.skipped_delta) for item in advances] == [(1, 0), (0, 1)]
