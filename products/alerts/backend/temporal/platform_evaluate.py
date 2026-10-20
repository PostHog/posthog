"""Temporal wiring for the platform's parallel insight evaluation.

The decisions live in `products/alerts/backend/platform_source_cycle.py`, so they stay plain
functions a test can call without Temporal.

One activity per admitted check, run side by side. A batch key is a team's alerts due in one
minute, and daily alerts in one timezone share their minute, so evaluating a key one check after
another would put the last check minutes behind the first.
"""

import asyncio
import datetime as dt
from collections.abc import Callable

from temporalio import activity, workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

from posthog.dataclasses import frozen
from posthog.temporal.common.base import PostHogWorkflow

with workflow.unsafe.imports_passed_through():
    from posthog.temporal.alerts.retry_policy import alert_timeouts
    from posthog.temporal.common.utils import close_db_connections

    from products.alerts_platform.backend.facade.contracts import (
        RECORD_OUTCOMES_ACTIVITY,
        AlertDeliveryRequest,
        PlatformAlertOutcome,
        SourceBatchEvaluation,
        SourceEvaluationInputs,
        SourceKind,
        SourceOutcomeInputs,
    )
    from products.alerts_platform.backend.facade.payload import outcome_chunks
    from products.alerts_platform.backend.facade.platform_metrics import increment_checks_unfinished, safe_record
    from products.alerts_platform.backend.facade.temporal import source_evaluation_timeout, start_deliveries

PLAN_START_TO_CLOSE = dt.timedelta(seconds=10)
PLAN_SCHEDULE_TO_CLOSE = dt.timedelta(seconds=20)
# Production's per-attempt budget for an hourly or slower check, so a query the parallel run
# gives up on is one production would have given up on as well.
CHECK_START_TO_CLOSE = alert_timeouts(None).evaluate_start_to_close
# Checks wait for a worker slot here. Derived rather than set, so queue time cannot shorten a
# check below its own budget.
CHECK_QUEUE_TOLERANCE = dt.timedelta(minutes=1)
CHECK_SCHEDULE_TO_CLOSE = CHECK_START_TO_CLOSE + CHECK_QUEUE_TOLERANCE
RECORD_START_TO_CLOSE = dt.timedelta(seconds=8)
RECORD_SCHEDULE_TO_CLOSE = dt.timedelta(seconds=12)
# The pool admits once per round, so a batch that admits only once evaluates at most one pool of
# checks per tick. Rounds refill the slots that finished checks free, the way production's
# scheduler does, until this budget ends. It stays under the one-minute tick.
ADMISSION_RUN_BUDGET = dt.timedelta(seconds=50)
ADMISSION_POLL_INTERVAL = dt.timedelta(seconds=2)
# What the source needs from its binding's `evaluation_timeout`. The checks run side by side, so
# the batch costs the admission rounds plus one check's budget, not one per check.
EVALUATION_BUDGET = PLAN_SCHEDULE_TO_CLOSE + ADMISSION_RUN_BUDGET + CHECK_SCHEDULE_TO_CLOSE + RECORD_SCHEDULE_TO_CLOSE
_PATCH_READMISSION = "platform-insight-readmission-2026-10"
# Runs started before it recorded every outcome in one activity, and replay must schedule the same.
_PATCH_CHUNKED_RECORD = "platform-insight-chunked-record-2026-10"


@frozen
class InsightBatchPlanInputs:
    evaluation: SourceEvaluationInputs
    expires_at: float
    exclude: tuple[str, ...] = ()


@frozen
class InsightCheckInputs:
    evaluation: SourceEvaluationInputs
    configuration_id: str
    held_until: float


@activity.defn
@close_db_connections
def plan_platform_insight_batch_activity(inputs: InsightBatchPlanInputs) -> list[str]:
    # Imported in the body: the workflow below forces this module to evaluate inside Temporal's
    # sandbox, which a Django model import trips.
    from products.alerts.backend.platform_source_cycle import plan_insight_batch  # noqa: PLC0415

    key = inputs.evaluation.batch_key
    return list(
        plan_insight_batch(
            key.team_id,
            key.slot,
            dt.datetime.fromisoformat(inputs.evaluation.cutoff),
            expires_at=inputs.expires_at,
            exclude=inputs.exclude,
        )
    )


@activity.defn
@close_db_connections
def plan_platform_insight_round_activity(inputs: InsightBatchPlanInputs) -> list[str]:
    """`plan_platform_insight_batch_activity` with `exclude`, under its own name. A worker still on
    the old code runs the old name and drops `exclude`, so the round path must not call that name."""
    from products.alerts.backend.platform_source_cycle import plan_insight_batch  # noqa: PLC0415

    key = inputs.evaluation.batch_key
    return list(
        plan_insight_batch(
            key.team_id,
            key.slot,
            dt.datetime.fromisoformat(inputs.evaluation.cutoff),
            expires_at=inputs.expires_at,
            exclude=inputs.exclude,
        )
    )


@activity.defn
@close_db_connections
def evaluate_platform_insight_check_activity(inputs: InsightCheckInputs) -> SourceBatchEvaluation | None:
    """Sync, so the thread this blocks is a slot Temporal is accounting for."""
    from products.alerts.backend.platform_source_cycle import evaluate_insight_check  # noqa: PLC0415

    info = activity.info()
    key = inputs.evaluation.batch_key
    return evaluate_insight_check(
        key.team_id,
        key.slot,
        dt.datetime.fromisoformat(inputs.evaluation.cutoff),
        inputs.configuration_id,
        held_until=inputs.held_until,
        evaluation_id=f"{info.workflow_run_id}:{info.activity_id}:{info.attempt}",
    )


@workflow.defn(name="insight-alert-platform-evaluate")
class InsightAlertPlatformEvaluateWorkflow(PostHogWorkflow):
    """Evaluates one batch key, records what it decided, and starts the deliveries its checks asked
    for. Only the alerts the insight source allowlists ask for one."""

    inputs_cls = SourceEvaluationInputs

    @workflow.run
    async def run(self, inputs: SourceEvaluationInputs) -> int:
        # From the workflow's clock, so a retried plan reuses the expiry and gets its slots back. A
        # check releases its slot only while the slot still carries this expiry.
        expires_at = (workflow.now() + source_evaluation_timeout(SourceKind.INSIGHT)).timestamp()
        if workflow.patched(_PATCH_READMISSION):
            settled = await self._evaluate_in_rounds(inputs, expires_at)
        else:
            admitted = await self._plan(
                inputs, expires_at, exclude=(), activity_fn=plan_platform_insight_batch_activity
            )
            settled = await asyncio.gather(
                *(self._check(inputs, configuration_id, expires_at) for configuration_id in admitted),
                return_exceptions=True,
            )
        if not settled:
            return 0

        for result in settled:
            # Only a check's own failure is a missing outcome. A cancellation or a bug in this
            # workflow would otherwise be recorded as a partial batch.
            if isinstance(result, BaseException) and not isinstance(result, ActivityError):
                raise result
        evaluations = [result for result in settled if isinstance(result, SourceBatchEvaluation)]
        outcomes: tuple[PlatformAlertOutcome, ...] = tuple(o for e in evaluations for o in e.outcomes)
        deliveries: tuple[AlertDeliveryRequest, ...] = tuple(d for e in evaluations for d in e.deliveries)
        if len(outcomes) < len(settled):
            workflow.logger.warning(
                "%d of %d platform insight checks reached no outcome", len(settled) - len(outcomes), len(settled)
            )
            safe_record(increment_checks_unfinished, SourceKind.INSIGHT.value, len(settled) - len(outcomes))
        if not outcomes:
            return 0

        # Each check's result fits a payload on its own, but the batch's together may not. A chunk's
        # deliveries start after its own record, so a later chunk that fails cannot strand them.
        chunks = outcome_chunks(outcomes) if workflow.patched(_PATCH_CHUNKED_RECORD) else [outcomes]
        for chunk in chunks:
            await workflow.execute_activity(
                RECORD_OUTCOMES_ACTIVITY,
                SourceOutcomeInputs(team_id=inputs.batch_key.team_id, cutoff=inputs.cutoff, outcomes=chunk),
                start_to_close_timeout=RECORD_START_TO_CLOSE,
                schedule_to_close_timeout=RECORD_SCHEDULE_TO_CLOSE,
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            # Started only after the record, because a delivery reads the history row the record writes.
            recorded = {str(outcome.configuration_id) for outcome in chunk}
            await start_deliveries([delivery for delivery in deliveries if delivery.configuration_id in recorded])
        return len(outcomes)

    async def _plan(
        self,
        inputs: SourceEvaluationInputs,
        expires_at: float,
        *,
        exclude: tuple[str, ...],
        activity_fn: Callable[[InsightBatchPlanInputs], list[str]],
    ) -> list[str]:
        return await workflow.execute_activity(
            activity_fn,
            InsightBatchPlanInputs(evaluation=inputs, expires_at=expires_at, exclude=exclude),
            start_to_close_timeout=PLAN_START_TO_CLOSE,
            schedule_to_close_timeout=PLAN_SCHEDULE_TO_CLOSE,
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

    async def _check(
        self, inputs: SourceEvaluationInputs, configuration_id: str, expires_at: float
    ) -> SourceBatchEvaluation | None:
        # One attempt each. A check that does not finish leaves no outcome, so it keeps its due time
        # and a later tick evaluates it again, the way a cohort the logs budget left out behaves.
        return await workflow.execute_activity(
            evaluate_platform_insight_check_activity,
            InsightCheckInputs(evaluation=inputs, configuration_id=configuration_id, held_until=expires_at),
            start_to_close_timeout=CHECK_START_TO_CLOSE,
            schedule_to_close_timeout=CHECK_SCHEDULE_TO_CLOSE,
            retry_policy=RetryPolicy(maximum_attempts=1),
        )

    async def _evaluate_in_rounds(
        self, inputs: SourceEvaluationInputs, expires_at: float
    ) -> list[SourceBatchEvaluation | None | BaseException]:
        """Admits and starts checks in rounds until a round adds nothing and none of this batch's
        checks still run, or until the admission budget ends."""
        started: dict[str, asyncio.Task[SourceBatchEvaluation | None]] = {}
        deadline = workflow.now() + ADMISSION_RUN_BUDGET
        while True:
            try:
                admitted = await self._plan(
                    inputs, expires_at, exclude=tuple(started), activity_fn=plan_platform_insight_round_activity
                )
            except ActivityError:
                if not started:
                    raise
                # The started checks still record. Their outcomes are lost if this failure ends the run.
                workflow.logger.warning("Stopped admitting platform insight checks after a failed plan")
                break
            for configuration_id in admitted:
                started[configuration_id] = asyncio.create_task(self._check(inputs, configuration_id, expires_at))
            running = [task for task in started.values() if not task.done()]
            if not running or workflow.now() >= deadline:
                break
            await asyncio.wait(
                running, timeout=ADMISSION_POLL_INTERVAL.total_seconds(), return_when=asyncio.FIRST_COMPLETED
            )
        return await asyncio.gather(*started.values(), return_exceptions=True)


PLATFORM_EVALUATION_WORKFLOWS = [InsightAlertPlatformEvaluateWorkflow]
PLATFORM_EVALUATION_ACTIVITIES = [
    plan_platform_insight_batch_activity,
    plan_platform_insight_round_activity,
    evaluate_platform_insight_check_activity,
]
