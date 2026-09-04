"""Backfill loop: walk a date window newest-first and start one evaluation child per unit.

The `EvaluationBackfill` row holds every piece of progress, so the workflow keeps no state of its
own. It runs one batch, sleeps a tick, then continues as new, which keeps the history short no
matter how long the window takes to drain.
"""

import asyncio
import hashlib
from dataclasses import replace
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any

from django.conf import settings
from django.db.models import F
from django.utils import timezone

import temporalio
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.workflow import ParentClosePolicy

from posthog.dataclasses import frozen
from posthog.models.team import Team
from posthog.sync import database_sync_to_async
from posthog.temporal.ai_observability.evaluation_types import EVALUATION_WORKFLOW_PREFIXES
from posthog.temporal.ai_observability.evaluation_workflow_activities import RunEvaluationInputs, as_utc_datetime
from posthog.temporal.ai_observability.run_aggregate_evaluation import RunAggregateEvaluationInputs
from posthog.temporal.common.base import PostHogWorkflow

from products.ai_observability.backend.backfill_candidates import fetch_backfill_candidates
from products.ai_observability.backend.models.evaluation_backfill import (
    ACTIVE_BACKFILL_STATUSES,
    EvaluationBackfill,
    EvaluationBackfillStatus,
)

BACKFILL_WORKFLOW_NAME = "llma-evaluation-backfill"
BACKFILL_TICK_INTERVAL = timedelta(seconds=60)
PREPARE_TICK_TIMEOUT = timedelta(seconds=30)
FIND_CANDIDATES_TIMEOUT = timedelta(seconds=120)
ADVANCE_CURSOR_TIMEOUT = timedelta(seconds=30)
FAIL_BACKFILL_TIMEOUT = timedelta(seconds=30)
# Long enough for the slowest child: a trace evaluation can settle for its 2 hour maximum age
# before the judge even starts.
CHILD_EXECUTION_TIMEOUT = timedelta(hours=3)

ACTIVITY_RETRY_POLICY = RetryPolicy(maximum_attempts=3)
# A tick that keeps failing would otherwise leave the row RUNNING and the loop spinning
# forever, so the backfill gives up and cancels itself.
BACKFILL_MAX_CONSECUTIVE_FAILURES = 5


def backfill_workflow_id(backfill_id: str) -> str:
    return f"{BACKFILL_WORKFLOW_NAME}-{backfill_id}"


@frozen
class EvaluationBackfillInputs:
    backfill_id: str
    team_id: int
    # Ticks that failed back to back. A successful tick resets it.
    consecutive_failures: int = 0


class TickAction(StrEnum):
    DISPATCH = "dispatch"
    # Terminal row, missing row, or an evaluation that can no longer run: the loop stops.
    FINISHED = "finished"


@frozen
class PrepareTickOutput:
    action: TickAction
    evaluation_id: str = ""
    target: str = "generation"
    evaluation_type: str = "hog"
    settle: dict[str, Any] | None = None
    rerun_existing: bool = False
    batch_size: int = 0


@frozen
class FindCandidatesInputs:
    backfill_id: str
    team_id: int
    limit: int


@frozen
class FindCandidatesOutput:
    # `BackfillCandidate` as a dict with an ISO `unit_timestamp`, so the page crosses the activity
    # boundary without a datetime round trip.
    candidates: list[dict[str, Any]]
    next_cursor_timestamp: str | None
    next_cursor_unit_id: str
    exhausted: bool
    # The cursor the walk started from, threaded into the advance so it can match on it.
    started_from_cursor_timestamp: str | None
    started_from_cursor_unit_id: str


@frozen
class AdvanceCursorInputs:
    backfill_id: str
    team_id: int
    expected_cursor_timestamp: str | None
    expected_cursor_unit_id: str
    new_cursor_timestamp: str | None
    new_cursor_unit_id: str
    dispatched_delta: int
    skipped_delta: int
    exhausted: bool


@frozen
class AdvanceCursorOutput:
    finished: bool


def _workflow_safe_id(value: str) -> str:
    # Trace and session ids are user-controlled and unbounded, so the live scheduler hashes long
    # ones to keep the workflow id valid. Backfill ids must collide with the live path's ids to
    # inherit its at-most-once guard, so the same threshold and hash apply here.
    return hashlib.md5(value.encode()).hexdigest() if len(value) > 128 else value


def child_workflow_name_and_id(
    *,
    evaluation_id: str,
    evaluation_type: str,
    target: str,
    unit_id: str,
    backfill_id: str,
    rerun_existing: bool,
) -> tuple[str, str]:
    if target == "generation":
        name = "run-evaluation"
        # The live scheduler suffixes "-ingestion"; matching it is what makes a unit the live path
        # already covered collide instead of running twice.
        workflow_id = f"{EVALUATION_WORKFLOW_PREFIXES[evaluation_type]}-{evaluation_id}-{unit_id}"
        live_suffix = "-ingestion"
    else:
        name = "run-aggregate-evaluation"
        workflow_id = f"llma-{target}-eval-{evaluation_id}-{_workflow_safe_id(unit_id)}"
        live_suffix = ""
    # A fresh id sidesteps the live path's at-most-once guard on purpose.
    workflow_id += f"-backfill-{backfill_id}" if rerun_existing else live_suffix
    return name, workflow_id


def _cancel_backfill(inputs: EvaluationBackfillInputs) -> None:
    EvaluationBackfill.objects.for_team(inputs.team_id).filter(
        pk=inputs.backfill_id, status=EvaluationBackfillStatus.RUNNING
    ).update(status=EvaluationBackfillStatus.CANCELLED, finished_at=timezone.now())


@temporalio.activity.defn
async def fail_evaluation_backfill_activity(inputs: EvaluationBackfillInputs) -> None:
    """Stop a backfill whose ticks keep failing, so the row does not stay RUNNING forever."""
    await database_sync_to_async(_cancel_backfill, thread_sensitive=False)(inputs)


def _prepare_backfill_tick(inputs: EvaluationBackfillInputs) -> PrepareTickOutput:
    row = (
        EvaluationBackfill.objects.for_team(inputs.team_id)
        .select_related("evaluation")
        .filter(pk=inputs.backfill_id)
        .first()
    )
    if row is None or row.status not in ACTIVE_BACKFILL_STATUSES:
        return PrepareTickOutput(action=TickAction.FINISHED)

    evaluation = row.evaluation
    # Three ways an evaluation can no longer produce a run, all ending the backfill. An unknown
    # evaluation type has no workflow id prefix, so no child could ever be started for it, and
    # cancelling here keeps that failure in an activity, where it is visible, rather than raising a
    # KeyError inside workflow code. A disabled evaluation is treated the same as a deleted one
    # because the loop has no event that would tell it the evaluation came back, so holding the
    # cursor would leave the row RUNNING and the workflow ticking forever.
    if evaluation.deleted or not evaluation.enabled or evaluation.evaluation_type not in EVALUATION_WORKFLOW_PREFIXES:
        _cancel_backfill(inputs)
        return PrepareTickOutput(action=TickAction.FINISHED)

    return PrepareTickOutput(
        action=TickAction.DISPATCH,
        evaluation_id=str(row.evaluation_id),
        # The row's target, not the evaluation's: an edit mid-run must not change what the walk
        # already dispatched against.
        target=row.target,
        evaluation_type=evaluation.evaluation_type,
        settle=evaluation.target_config,
        rerun_existing=row.rerun_existing,
        batch_size=settings.LLMA_EVAL_BACKFILL_BATCH_SIZE,
    )


@temporalio.activity.defn
async def prepare_evaluation_backfill_tick_activity(inputs: EvaluationBackfillInputs) -> PrepareTickOutput:
    return await database_sync_to_async(_prepare_backfill_tick, thread_sensitive=False)(inputs)


def _find_backfill_candidates(inputs: FindCandidatesInputs) -> FindCandidatesOutput:
    row = EvaluationBackfill.objects.for_team(inputs.team_id).get(pk=inputs.backfill_id)
    team = Team.objects.get(pk=inputs.team_id)
    page = fetch_backfill_candidates(
        team=team,
        evaluation_id=str(row.evaluation_id),
        target=row.target,
        conditions=row.conditions,
        window_start=row.window_start,
        window_end=row.window_end,
        rerun_existing=row.rerun_existing,
        cursor_timestamp=row.cursor_timestamp,
        cursor_unit_id=row.cursor_unit_id,
        limit=inputs.limit,
    )
    return FindCandidatesOutput(
        candidates=[
            {
                "unit_id": candidate.unit_id,
                "unit_timestamp": as_utc_datetime(candidate.unit_timestamp).isoformat(),
                "distinct_id": candidate.distinct_id,
                "session_id": candidate.session_id,
                "trace_id": candidate.trace_id,
            }
            for candidate in page.candidates
        ],
        next_cursor_timestamp=(
            # ClickHouse hands back naive datetimes; the cursor is compared against a
            # tz-aware column, so it has to be stamped before it is written back.
            as_utc_datetime(page.next_cursor_timestamp).isoformat() if page.next_cursor_timestamp else None
        ),
        next_cursor_unit_id=page.next_cursor_unit_id,
        exhausted=page.exhausted,
        started_from_cursor_timestamp=row.cursor_timestamp.isoformat() if row.cursor_timestamp else None,
        started_from_cursor_unit_id=row.cursor_unit_id,
    )


@temporalio.activity.defn
async def find_evaluation_backfill_candidates_activity(inputs: FindCandidatesInputs) -> FindCandidatesOutput:
    return await database_sync_to_async(_find_backfill_candidates, thread_sensitive=False)(inputs)


def _advance_backfill_cursor(inputs: AdvanceCursorInputs) -> AdvanceCursorOutput:
    updates: dict[str, Any] = {
        "dispatched_count": F("dispatched_count") + inputs.dispatched_delta,
        "skipped_count": F("skipped_count") + inputs.skipped_delta,
    }
    if inputs.new_cursor_timestamp is not None:
        updates["cursor_timestamp"] = datetime.fromisoformat(inputs.new_cursor_timestamp)
        updates["cursor_unit_id"] = inputs.new_cursor_unit_id
    if inputs.exhausted:
        updates["status"] = EvaluationBackfillStatus.COMPLETED
        updates["finished_at"] = timezone.now()

    expected_timestamp = (
        datetime.fromisoformat(inputs.expected_cursor_timestamp) if inputs.expected_cursor_timestamp else None
    )
    # Matching the starting cursor makes this idempotent: Temporal retries an activity whose
    # result was lost after it committed, and a second blind increment would inflate progress.
    # Filtering on RUNNING lets a concurrent cancel win over the advance.
    updated = (
        EvaluationBackfill.objects.for_team(inputs.team_id)
        .filter(
            pk=inputs.backfill_id,
            status=EvaluationBackfillStatus.RUNNING,
            cursor_timestamp=expected_timestamp,
            cursor_unit_id=inputs.expected_cursor_unit_id,
        )
        .update(**updates)
    )
    if updated:
        return AdvanceCursorOutput(finished=inputs.exhausted)
    # Zero rows has two causes that end differently. If the row is no longer RUNNING, someone
    # cancelled or completed it and the loop stops. If it is still RUNNING, an earlier attempt of
    # this same advance already committed and only its result was lost, so the loop must carry on
    # from the stored cursor instead of stalling with the window half walked.
    status = (
        EvaluationBackfill.objects.for_team(inputs.team_id)
        .filter(pk=inputs.backfill_id)
        .values_list("status", flat=True)
        .first()
    )
    return AdvanceCursorOutput(finished=status != EvaluationBackfillStatus.RUNNING)


@temporalio.activity.defn
async def advance_evaluation_backfill_cursor_activity(inputs: AdvanceCursorInputs) -> AdvanceCursorOutput:
    return await database_sync_to_async(_advance_backfill_cursor, thread_sensitive=False)(inputs)


@temporalio.workflow.defn(name=BACKFILL_WORKFLOW_NAME)
class EvaluationBackfillWorkflow(PostHogWorkflow):
    inputs_cls = EvaluationBackfillInputs

    @temporalio.workflow.run
    async def run(self, inputs: EvaluationBackfillInputs) -> None:
        tick = await temporalio.workflow.execute_activity(
            prepare_evaluation_backfill_tick_activity,
            inputs,
            start_to_close_timeout=PREPARE_TICK_TIMEOUT,
            retry_policy=ACTIVITY_RETRY_POLICY,
        )
        if tick.action == TickAction.FINISHED:
            return

        try:
            finished = await self._dispatch_batch(inputs, tick)
        except Exception:
            await self._handle_failed_tick(inputs)
            return
        if finished:
            return

        await asyncio.sleep(BACKFILL_TICK_INTERVAL.total_seconds())
        # One batch per run keeps the history short; the row carries all state across runs.
        temporalio.workflow.continue_as_new(replace(inputs, consecutive_failures=0))

    async def _dispatch_batch(self, inputs: EvaluationBackfillInputs, tick: PrepareTickOutput) -> bool:
        """Walk one page, start a child per unit, and advance the cursor. True ends the loop."""
        found = await temporalio.workflow.execute_activity(
            find_evaluation_backfill_candidates_activity,
            FindCandidatesInputs(backfill_id=inputs.backfill_id, team_id=inputs.team_id, limit=tick.batch_size),
            start_to_close_timeout=FIND_CANDIDATES_TIMEOUT,
            retry_policy=ACTIVITY_RETRY_POLICY,
        )
        started = await asyncio.gather(*(self._start_child(inputs, tick, candidate) for candidate in found.candidates))
        skipped = started.count(False)
        advance = await temporalio.workflow.execute_activity(
            advance_evaluation_backfill_cursor_activity,
            AdvanceCursorInputs(
                backfill_id=inputs.backfill_id,
                team_id=inputs.team_id,
                expected_cursor_timestamp=found.started_from_cursor_timestamp,
                expected_cursor_unit_id=found.started_from_cursor_unit_id,
                new_cursor_timestamp=found.next_cursor_timestamp,
                new_cursor_unit_id=found.next_cursor_unit_id,
                dispatched_delta=len(started) - skipped,
                skipped_delta=skipped,
                exhausted=found.exhausted,
            ),
            start_to_close_timeout=ADVANCE_CURSOR_TIMEOUT,
            retry_policy=ACTIVITY_RETRY_POLICY,
        )
        return advance.finished

    async def _handle_failed_tick(self, inputs: EvaluationBackfillInputs) -> None:
        failures = inputs.consecutive_failures + 1
        temporalio.workflow.logger.exception(
            "llma.evaluation_backfill_tick_failed",
            extra={"backfill_id": inputs.backfill_id, "consecutive_failures": failures},
        )
        if failures >= BACKFILL_MAX_CONSECUTIVE_FAILURES:
            await temporalio.workflow.execute_activity(
                fail_evaluation_backfill_activity,
                inputs,
                start_to_close_timeout=FAIL_BACKFILL_TIMEOUT,
                retry_policy=ACTIVITY_RETRY_POLICY,
            )
            return
        await asyncio.sleep(BACKFILL_TICK_INTERVAL.total_seconds())
        temporalio.workflow.continue_as_new(replace(inputs, consecutive_failures=failures))

    async def _start_child(
        self, inputs: EvaluationBackfillInputs, tick: PrepareTickOutput, candidate: dict[str, Any]
    ) -> bool:
        """Start one evaluation child. False means the unit already had a run, so it was skipped."""
        unit_id = candidate["unit_id"]
        name, workflow_id = child_workflow_name_and_id(
            evaluation_id=tick.evaluation_id,
            evaluation_type=tick.evaluation_type,
            target=tick.target,
            unit_id=unit_id,
            backfill_id=inputs.backfill_id,
            rerun_existing=tick.rerun_existing,
        )
        args: RunEvaluationInputs | RunAggregateEvaluationInputs
        if tick.target == "generation":
            args = RunEvaluationInputs(
                evaluation_id=tick.evaluation_id,
                # The child fetches the generation itself; the trace id and timestamp narrow
                # its scan.
                event_data={
                    "uuid": unit_id,
                    "team_id": inputs.team_id,
                    "timestamp": candidate["unit_timestamp"],
                    "trace_id": candidate["trace_id"],
                },
                backfill_id=inputs.backfill_id,
            )
        else:
            args = RunAggregateEvaluationInputs(
                evaluation_id=tick.evaluation_id,
                team_id=inputs.team_id,
                trace_id=unit_id if tick.target == "trace" else "",
                distinct_id=candidate["distinct_id"],
                session_id=candidate["session_id"],
                ai_session_id=unit_id if tick.target == "session" else None,
                target=tick.target,
                settle=tick.settle,
                # A historical unit is settled already, so the child skips its settling phase and
                # aggregates from this anchor.
                anchor_timestamp=candidate["unit_timestamp"],
                backfill_id=inputs.backfill_id,
            )
        try:
            await temporalio.workflow.start_child_workflow(
                name,
                args,
                id=workflow_id,
                task_queue=settings.LLMA_EVALS_TASK_QUEUE,
                id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
                parent_close_policy=ParentClosePolicy.ABANDON,
                execution_timeout=CHILD_EXECUTION_TIMEOUT,
            )
            return True
        except WorkflowAlreadyStartedError:
            return False
