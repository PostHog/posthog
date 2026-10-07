"""Temporal wiring for billing alert evaluation on the shared alerts platform.

The evaluation itself lives in `products/billing_alerts/backend/platform_source_cycle.py`, so it
stays a plain function a test can call without Temporal.
"""

import datetime as dt

from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow

with workflow.unsafe.imports_passed_through():
    from posthog.temporal.common.utils import close_db_connections

    from products.alerts_platform.backend.facade.contracts import (
        RECORD_OUTCOMES_ACTIVITY,
        SourceBatchEvaluation,
        SourceEvaluationInputs,
        SourceOutcomeInputs,
    )

WORKFLOW_NAME = "billing-alert-platform-evaluate"

# One billing service call per organization in the batch, so the budget covers several calls.
EVALUATE_START_TO_CLOSE = dt.timedelta(seconds=60)
EVALUATE_SCHEDULE_TO_CLOSE = EVALUATE_START_TO_CLOSE + dt.timedelta(seconds=20)
RECORD_START_TO_CLOSE = dt.timedelta(seconds=8)
RECORD_SCHEDULE_TO_CLOSE = dt.timedelta(seconds=12)
# What the source needs from its binding's `evaluation_timeout`.
EVALUATION_BUDGET = EVALUATE_SCHEDULE_TO_CLOSE + RECORD_SCHEDULE_TO_CLOSE


@activity.defn
@close_db_connections
def evaluate_billing_alerts_activity(inputs: SourceEvaluationInputs) -> SourceBatchEvaluation:
    # Imported in the activity body, because the workflow below forces this module to evaluate
    # inside Temporal's sandbox, which a Django model import trips.
    from products.billing_alerts.backend.platform_source_cycle import evaluate_billing_batch  # noqa: PLC0415

    return evaluate_billing_batch(
        inputs.batch_key.team_id, inputs.batch_key.slot, dt.datetime.fromisoformat(inputs.cutoff)
    )


@workflow.defn(name=WORKFLOW_NAME)
class BillingAlertPlatformEvaluateWorkflow(PostHogWorkflow):
    """Evaluates one batch key and records what it decided. Delivers nothing, and writes only the
    shared platform's own rows: billing's own stack owns the billing tables."""

    inputs_cls = SourceEvaluationInputs

    @workflow.run
    async def run(self, inputs: SourceEvaluationInputs) -> int:
        # One attempt. A failed batch keeps its due time, so the next tick reaches it anyway.
        evaluation = await workflow.execute_activity(
            evaluate_billing_alerts_activity,
            inputs,
            start_to_close_timeout=EVALUATE_START_TO_CLOSE,
            schedule_to_close_timeout=EVALUATE_SCHEDULE_TO_CLOSE,
            retry_policy=RetryPolicy(maximum_attempts=1),
        )
        if not evaluation.outcomes:
            return 0
        return await workflow.execute_activity(
            RECORD_OUTCOMES_ACTIVITY,
            SourceOutcomeInputs(team_id=inputs.batch_key.team_id, cutoff=inputs.cutoff, outcomes=evaluation.outcomes),
            start_to_close_timeout=RECORD_START_TO_CLOSE,
            schedule_to_close_timeout=RECORD_SCHEDULE_TO_CLOSE,
            retry_policy=RetryPolicy(maximum_attempts=3),
            result_type=int,
        )


PLATFORM_EVALUATION_WORKFLOWS = [BillingAlertPlatformEvaluateWorkflow]
PLATFORM_EVALUATION_ACTIVITIES = [evaluate_billing_alerts_activity]
