import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from unittest.mock import AsyncMock, patch

from django.conf import settings
from django.test import override_settings

from asgiref.sync import async_to_sync
from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.workflow import ParentClosePolicy

from posthog.models import Organization, Team
from posthog.temporal.ai_observability.evaluation_backfill import (
    BACKFILL_MAX_CONSECUTIVE_FAILURES,
    AdvanceCursorInputs,
    AdvanceCursorOutput,
    EvaluationBackfillInputs,
    EvaluationBackfillWorkflow,
    FindCandidatesInputs,
    FindCandidatesOutput,
    PrepareTickOutput,
    TickAction,
    advance_evaluation_backfill_cursor_activity,
    child_workflow_name_and_id,
    fail_evaluation_backfill_activity,
    find_evaluation_backfill_candidates_activity,
    prepare_evaluation_backfill_tick_activity,
)
from posthog.temporal.ai_observability.evaluation_workflow_activities import RunEvaluationInputs
from posthog.temporal.ai_observability.run_aggregate_evaluation import RunAggregateEvaluationInputs

from products.ai_observability.backend.backfill_candidates import BackfillCandidate, CandidatePage
from products.ai_observability.backend.models.evaluation_backfill import EvaluationBackfill, EvaluationBackfillStatus
from products.ai_observability.backend.models.evaluations import Evaluation

WINDOW_START = datetime(2026, 1, 1, tzinfo=UTC)
WINDOW_END = datetime(2026, 2, 1, tzinfo=UTC)
UNIT_TIMESTAMP = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)


class _BackfillMocks:
    def __init__(
        self,
        *,
        activity_results: dict | None = None,
        child_errors_for_ids: dict[str, Exception] | None = None,
    ) -> None:
        self.activity_results = activity_results or {}
        self.child_errors_for_ids = child_errors_for_ids or {}
        self.activity_calls: list[tuple] = []
        self.child_calls: list[dict] = []

    async def execute_activity(self, activity_fn, activity_input, **_) -> object:
        self.activity_calls.append((activity_fn, activity_input))
        result = self.activity_results.get(activity_fn)
        if isinstance(result, Exception):
            raise result
        if activity_fn is advance_evaluation_backfill_cursor_activity and activity_fn not in self.activity_results:
            return AdvanceCursorOutput(finished=False)
        return result

    async def start_child_workflow(self, *args, **kwargs) -> object:
        wid = kwargs.get("id")
        self.child_calls.append(
            {"name": args[0], "id": wid, "inputs": args[1] if len(args) > 1 else None, "kwargs": kwargs}
        )
        if wid is not None and wid in self.child_errors_for_ids:
            raise self.child_errors_for_ids[wid]
        return object()


def _inputs() -> EvaluationBackfillInputs:
    return EvaluationBackfillInputs(backfill_id="B", team_id=42)


def _candidate(unit_id: str) -> dict[str, Any]:
    return {
        "unit_id": unit_id,
        "unit_timestamp": UNIT_TIMESTAMP.isoformat(),
        "distinct_id": f"distinct-{unit_id}",
        "session_id": f"web-{unit_id}",
        "trace_id": f"trace-{unit_id}",
    }


def _found(candidates: list[dict[str, Any]], *, exhausted: bool = False) -> FindCandidatesOutput:
    return FindCandidatesOutput(
        candidates=candidates,
        next_cursor_timestamp=UNIT_TIMESTAMP.isoformat(),
        next_cursor_unit_id=candidates[-1]["unit_id"] if candidates else "",
        exhausted=exhausted,
        started_from_cursor_timestamp=None,
        started_from_cursor_unit_id="",
    )


async def _run(mocks: _BackfillMocks, inputs: EvaluationBackfillInputs | None = None):
    # `workflow.logger` reaches into the workflow runtime, which isn't set up here.
    fake_logger = type("Logger", (), {"exception": staticmethod(lambda *_a, **_kw: None)})()
    with (
        patch("temporalio.workflow.logger", fake_logger),
        patch("temporalio.workflow.execute_activity", side_effect=mocks.execute_activity),
        patch("temporalio.workflow.start_child_workflow", side_effect=mocks.start_child_workflow),
        patch("temporalio.workflow.continue_as_new") as continue_as_new,
        patch("asyncio.sleep", new=AsyncMock()),
    ):
        await EvaluationBackfillWorkflow().run(inputs or _inputs())
    return continue_as_new


def _called(mocks: _BackfillMocks) -> list:
    return [fn for fn, _ in mocks.activity_calls]


def _advance_input(mocks: _BackfillMocks) -> AdvanceCursorInputs:
    return next(call for fn, call in mocks.activity_calls if fn is advance_evaluation_backfill_cursor_activity)


class TestEvaluationBackfillWorkflow:
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
                prepare_evaluation_backfill_tick_activity: PrepareTickOutput(
                    action=TickAction.DISPATCH, evaluation_id="E", batch_size=100
                ),
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
                prepare_evaluation_backfill_tick_activity: PrepareTickOutput(
                    action=TickAction.DISPATCH, evaluation_id="E", batch_size=100
                ),
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
    async def test_exhausted_page_finishes_without_continue_as_new(self) -> None:
        mocks = _BackfillMocks(
            activity_results={
                prepare_evaluation_backfill_tick_activity: PrepareTickOutput(
                    action=TickAction.DISPATCH, evaluation_id="E", batch_size=100
                ),
                find_evaluation_backfill_candidates_activity: _found([_candidate("u1")], exhausted=True),
                advance_evaluation_backfill_cursor_activity: AdvanceCursorOutput(finished=True),
            }
        )

        continue_as_new = await _run(mocks)

        assert _advance_input(mocks).exhausted
        continue_as_new.assert_not_called()

    @pytest.mark.asyncio
    async def test_failing_tick_continues_as_new_with_an_incremented_failure_count(self) -> None:
        mocks = _BackfillMocks(
            activity_results={
                prepare_evaluation_backfill_tick_activity: PrepareTickOutput(
                    action=TickAction.DISPATCH, batch_size=100
                ),
                find_evaluation_backfill_candidates_activity: RuntimeError("clickhouse is down"),
            }
        )

        continue_as_new = await _run(mocks, EvaluationBackfillInputs(backfill_id="B", team_id=42))

        assert fail_evaluation_backfill_activity not in _called(mocks)
        continue_as_new.assert_called_once_with(
            EvaluationBackfillInputs(backfill_id="B", team_id=42, consecutive_failures=1)
        )

    @pytest.mark.asyncio
    async def test_repeated_failures_cancel_the_backfill_instead_of_looping_forever(self) -> None:
        mocks = _BackfillMocks(
            activity_results={
                prepare_evaluation_backfill_tick_activity: PrepareTickOutput(
                    action=TickAction.DISPATCH, batch_size=100
                ),
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
                prepare_evaluation_backfill_tick_activity: PrepareTickOutput(
                    action=TickAction.DISPATCH,
                    evaluation_id="E",
                    target=target,
                    settle={"window_seconds": 30},
                    batch_size=100,
                ),
                find_evaluation_backfill_candidates_activity: _found([_candidate("u1")]),
            }
        )

        await _run(mocks)

        assert mocks.child_calls[0]["inputs"] == expected


@pytest.mark.parametrize(
    "target,evaluation_type,rerun_existing,expected_name,expected_id",
    [
        ("generation", "hog", False, "run-evaluation", "llma-hog-eval-E-U-ingestion"),
        ("generation", "llm_judge", True, "run-evaluation", "llma-llm-eval-E-U-backfill-B"),
        ("trace", "hog", False, "run-aggregate-evaluation", "llma-trace-eval-E-U"),
        ("session", "hog", False, "run-aggregate-evaluation", "llma-session-eval-E-U"),
        ("trace", "hog", True, "run-aggregate-evaluation", "llma-trace-eval-E-U-backfill-B"),
    ],
)
def test_child_workflow_ids_match_live_scheduler_unless_rerun(
    target, evaluation_type, rerun_existing, expected_name, expected_id
) -> None:
    name, workflow_id = child_workflow_name_and_id(
        evaluation_id="E",
        evaluation_type=evaluation_type,
        target=target,
        unit_id="U",
        backfill_id="B",
        rerun_existing=rerun_existing,
    )

    assert (name, workflow_id) == (expected_name, expected_id)


def test_long_unit_ids_are_hashed_like_the_live_scheduler() -> None:
    # 32 hex characters is the md5 the Node scheduler falls back to past 128 characters; without
    # the same fallback a backfill child would not collide with the live path's workflow id.
    _, workflow_id = child_workflow_name_and_id(
        evaluation_id="E",
        evaluation_type="hog",
        target="trace",
        unit_id="t" * 129,
        backfill_id="B",
        rerun_existing=False,
    )

    assert workflow_id == "llma-trace-eval-E-4670e99bfd94a7cdfa2de20b9a018676"


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


def _activity_inputs(backfill_data) -> EvaluationBackfillInputs:
    return EvaluationBackfillInputs(backfill_id=str(backfill_data["backfill"].id), team_id=backfill_data["team"].id)


@pytest.mark.django_db(transaction=True)
class TestEvaluationBackfillActivities:
    @pytest.mark.parametrize("status", [EvaluationBackfillStatus.COMPLETED, EvaluationBackfillStatus.CANCELLED, None])
    def test_prepare_returns_finished_for_missing_or_terminal_row(self, backfill_data, status) -> None:
        inputs = _activity_inputs(backfill_data)
        if status is None:
            inputs = EvaluationBackfillInputs(backfill_id=str(uuid.uuid4()), team_id=backfill_data["team"].id)
        else:
            EvaluationBackfill.objects.for_team(backfill_data["team"].id).filter(
                pk=backfill_data["backfill"].id
            ).update(status=status)

        result = async_to_sync(prepare_evaluation_backfill_tick_activity)(inputs)

        assert result.action == TickAction.FINISHED

    @pytest.mark.parametrize(
        "update",
        [
            {"deleted": True},
            # No workflow id prefix exists for this type, so no child could ever be started.
            {"evaluation_type": "not_a_real_type"},
            # Nothing tells the loop a paused evaluation came back, so holding the cursor would
            # leave the row RUNNING and the workflow ticking forever.
            {"enabled": False},
        ],
    )
    def test_prepare_cancels_the_row_when_the_evaluation_cannot_run(self, backfill_data, update) -> None:
        Evaluation.objects.filter(pk=backfill_data["evaluation"].id).update(**update)

        result = async_to_sync(prepare_evaluation_backfill_tick_activity)(_activity_inputs(backfill_data))

        assert result.action == TickAction.FINISHED
        backfill_data["backfill"].refresh_from_db()
        assert backfill_data["backfill"].status == EvaluationBackfillStatus.CANCELLED
        assert backfill_data["backfill"].finished_at is not None

    def test_prepare_dispatches_with_configured_batch_size(self, backfill_data) -> None:
        with override_settings(LLMA_EVAL_BACKFILL_BATCH_SIZE=7):
            result = async_to_sync(prepare_evaluation_backfill_tick_activity)(_activity_inputs(backfill_data))

        assert result == PrepareTickOutput(
            action=TickAction.DISPATCH,
            evaluation_id=str(backfill_data["evaluation"].id),
            target="generation",
            evaluation_type="hog",
            # A generation evaluation carries no settle config; the model normalizes the bag to {}.
            settle={},
            rerun_existing=False,
            batch_size=7,
        )

    def test_find_serializes_candidates_and_cursor(self, backfill_data) -> None:
        EvaluationBackfill.objects.for_team(backfill_data["team"].id).filter(pk=backfill_data["backfill"].id).update(
            cursor_timestamp=UNIT_TIMESTAMP + timedelta(hours=1), cursor_unit_id="u0"
        )
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
            {
                "unit_id": "u1",
                "unit_timestamp": UNIT_TIMESTAMP.isoformat(),
                "distinct_id": "d1",
                "session_id": "web-1",
                "trace_id": "t1",
            }
        ]
        assert (result.next_cursor_timestamp, result.next_cursor_unit_id) == (UNIT_TIMESTAMP.isoformat(), "u1")
        assert (result.started_from_cursor_timestamp, result.started_from_cursor_unit_id) == (
            (UNIT_TIMESTAMP + timedelta(hours=1)).isoformat(),
            "u0",
        )
        assert result.exhausted

    def test_advance_is_idempotent_on_retry(self, backfill_data) -> None:
        advance = AdvanceCursorInputs(
            backfill_id=str(backfill_data["backfill"].id),
            team_id=backfill_data["team"].id,
            expected_cursor_timestamp=None,
            expected_cursor_unit_id="",
            new_cursor_timestamp=UNIT_TIMESTAMP.isoformat(),
            new_cursor_unit_id="u3",
            dispatched_delta=3,
            skipped_delta=1,
            exhausted=False,
        )

        first = async_to_sync(advance_evaluation_backfill_cursor_activity)(advance)
        second = async_to_sync(advance_evaluation_backfill_cursor_activity)(advance)

        backfill_data["backfill"].refresh_from_db()
        assert (backfill_data["backfill"].dispatched_count, backfill_data["backfill"].skipped_count) == (3, 1)
        assert backfill_data["backfill"].cursor_unit_id == "u3"
        assert not first.finished
        # The second call matched nothing because the first already moved the cursor. Reading that
        # as finished would end the loop with the row still RUNNING and the window half walked.
        assert not second.finished

    def test_advance_marks_completed_when_exhausted(self, backfill_data) -> None:
        result = async_to_sync(advance_evaluation_backfill_cursor_activity)(
            AdvanceCursorInputs(
                backfill_id=str(backfill_data["backfill"].id),
                team_id=backfill_data["team"].id,
                expected_cursor_timestamp=None,
                expected_cursor_unit_id="",
                new_cursor_timestamp=UNIT_TIMESTAMP.isoformat(),
                new_cursor_unit_id="u3",
                dispatched_delta=1,
                skipped_delta=0,
                exhausted=True,
            )
        )

        assert result.finished
        backfill_data["backfill"].refresh_from_db()
        assert backfill_data["backfill"].status == EvaluationBackfillStatus.COMPLETED
        assert backfill_data["backfill"].finished_at is not None

    def test_advance_loses_to_concurrent_cancel(self, backfill_data) -> None:
        EvaluationBackfill.objects.for_team(backfill_data["team"].id).filter(pk=backfill_data["backfill"].id).update(
            status=EvaluationBackfillStatus.CANCELLED
        )

        result = async_to_sync(advance_evaluation_backfill_cursor_activity)(
            AdvanceCursorInputs(
                backfill_id=str(backfill_data["backfill"].id),
                team_id=backfill_data["team"].id,
                expected_cursor_timestamp=None,
                expected_cursor_unit_id="",
                new_cursor_timestamp=UNIT_TIMESTAMP.isoformat(),
                new_cursor_unit_id="u3",
                dispatched_delta=1,
                skipped_delta=0,
                exhausted=False,
            )
        )

        assert result.finished
        backfill_data["backfill"].refresh_from_db()
        assert backfill_data["backfill"].status == EvaluationBackfillStatus.CANCELLED
        assert backfill_data["backfill"].dispatched_count == 0
