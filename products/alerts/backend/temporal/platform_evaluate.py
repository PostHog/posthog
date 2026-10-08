"""Temporal wiring for the platform's parallel insight evaluation.

The decisions live in `products/alerts/backend/platform_source_cycle.py`, so they stay plain
functions a test can call without Temporal.

One activity per admitted check, run side by side. A batch key is a team's alerts due in one
minute, and daily alerts in one timezone share their minute, so evaluating a key one check after
another would put the last check minutes behind the first.
"""

import asyncio
import datetime as dt

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
        PlatformAlertOutcome,
        SourceEvaluationInputs,
        SourceKind,
        SourceOutcomeInputs,
    )
    from products.alerts_platform.backend.facade.temporal import source_evaluation_timeout

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
# What the source needs from its binding's `evaluation_timeout`. The checks run side by side, so
# the batch costs one check's budget, not one per check.
EVALUATION_BUDGET = PLAN_SCHEDULE_TO_CLOSE + CHECK_SCHEDULE_TO_CLOSE + RECORD_SCHEDULE_TO_CLOSE


@frozen
class InsightBatchPlanInputs:
    evaluation: SourceEvaluationInputs
    expires_at: float


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
            key.team_id, key.slot, dt.datetime.fromisoformat(inputs.evaluation.cutoff), expires_at=inputs.expires_at
        )
    )


@activity.defn
@close_db_connections
def evaluate_platform_insight_check_activity(inputs: InsightCheckInputs) -> PlatformAlertOutcome | None:
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
    """Evaluates one batch key and records what it decided. Starts no deliveries: the production
    insight fleet is the only stack that notifies anyone."""

    inputs_cls = SourceEvaluationInputs

    @workflow.run
    async def run(self, inputs: SourceEvaluationInputs) -> int:
        # From the workflow's clock, so a retried plan reuses the expiry and gets its slots back. A
        # check releases its slot only while the slot still carries this expiry.
        expires_at = (workflow.now() + source_evaluation_timeout(SourceKind.INSIGHT)).timestamp()
        admitted = await workflow.execute_activity(
            plan_platform_insight_batch_activity,
            InsightBatchPlanInputs(evaluation=inputs, expires_at=expires_at),
            start_to_close_timeout=PLAN_START_TO_CLOSE,
            schedule_to_close_timeout=PLAN_SCHEDULE_TO_CLOSE,
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        if not admitted:
            return 0

        # One attempt each. A check that does not finish leaves no outcome, so it keeps its due time
        # and a later tick evaluates it again, the way a cohort the logs budget left out behaves.
        settled = await asyncio.gather(
            *(
                workflow.execute_activity(
                    evaluate_platform_insight_check_activity,
                    InsightCheckInputs(evaluation=inputs, configuration_id=configuration_id, held_until=expires_at),
                    start_to_close_timeout=CHECK_START_TO_CLOSE,
                    schedule_to_close_timeout=CHECK_SCHEDULE_TO_CLOSE,
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )
                for configuration_id in admitted
            ),
            return_exceptions=True,
        )
        for result in settled:
            # Only a check's own failure is a missing outcome. A cancellation or a bug in this
            # workflow would otherwise be recorded as a partial batch.
            if isinstance(result, BaseException) and not isinstance(result, ActivityError):
                raise result
        outcomes = tuple(outcome for outcome in settled if isinstance(outcome, PlatformAlertOutcome))
        if len(outcomes) < len(settled):
            workflow.logger.warning(
                "%d of %d platform insight checks reached no outcome", len(settled) - len(outcomes), len(settled)
            )
        if not outcomes:
            return 0

        await workflow.execute_activity(
            RECORD_OUTCOMES_ACTIVITY,
            SourceOutcomeInputs(team_id=inputs.batch_key.team_id, cutoff=inputs.cutoff, outcomes=outcomes),
            start_to_close_timeout=RECORD_START_TO_CLOSE,
            schedule_to_close_timeout=RECORD_SCHEDULE_TO_CLOSE,
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        return len(outcomes)


PLATFORM_EVALUATION_WORKFLOWS = [InsightAlertPlatformEvaluateWorkflow]
PLATFORM_EVALUATION_ACTIVITIES = [plan_platform_insight_batch_activity, evaluate_platform_insight_check_activity]
