"""Temporal wiring for appearance alerts, which the platform evaluates for every source.

The evaluation lives in `logic/appearance.py`, so a test can call it without Temporal.
"""

import datetime as dt

from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow

from products.alerts_platform.backend.temporal.outcomes import alerts_platform_record_outcomes_activity
from products.alerts_platform.backend.temporal.sources import APPEARANCE_WORKFLOW_NAME
from products.alerts_platform.backend.temporal.workflows import start_deliveries

with workflow.unsafe.imports_passed_through():
    from posthog.temporal.common.utils import close_db_connections

    from products.alerts_platform.backend.facade.contracts import (
        SourceBatchEvaluation,
        SourceEvaluationInputs,
        SourceOutcomeInputs,
    )
    from products.alerts_platform.backend.facade.payload import outcome_chunks

EVALUATE_START_TO_CLOSE = dt.timedelta(seconds=40)
EVALUATE_SCHEDULE_TO_CLOSE = dt.timedelta(seconds=60)
RECORD_START_TO_CLOSE = dt.timedelta(seconds=8)
RECORD_SCHEDULE_TO_CLOSE = dt.timedelta(seconds=12)


@activity.defn
@close_db_connections
def evaluate_appearance_alerts_activity(inputs: SourceEvaluationInputs) -> SourceBatchEvaluation:
    """Sync, so the thread this blocks is a slot the worker's activity executor accounts for."""
    # Imported in the body, because the workflow below makes this module load inside Temporal's
    # sandbox, which refuses a Django model import.
    from products.alerts_platform.backend.logic.appearance import evaluate_appearance_batch  # noqa: PLC0415

    return evaluate_appearance_batch(
        inputs.source, inputs.batch_key.team_id, inputs.batch_key.slot, dt.datetime.fromisoformat(inputs.cutoff)
    )


@workflow.defn(name=APPEARANCE_WORKFLOW_NAME)
class AppearanceAlertEvaluateWorkflow(PostHogWorkflow):
    """Evaluates one batch key of one source's appearance alerts, records it, and starts its deliveries."""

    inputs_cls = SourceEvaluationInputs

    @workflow.run
    async def run(self, inputs: SourceEvaluationInputs) -> int:
        # One attempt. A lost attempt records nothing, so the window stays where it was and the next tick reads it.
        evaluation = await workflow.execute_activity(
            evaluate_appearance_alerts_activity,
            inputs,
            start_to_close_timeout=EVALUATE_START_TO_CLOSE,
            schedule_to_close_timeout=EVALUATE_SCHEDULE_TO_CLOSE,
            retry_policy=RetryPolicy(maximum_attempts=1),
        )
        started = 0
        for chunk in outcome_chunks(evaluation.outcomes):
            await workflow.execute_activity(
                alerts_platform_record_outcomes_activity,
                SourceOutcomeInputs(team_id=inputs.batch_key.team_id, cutoff=inputs.cutoff, outcomes=chunk),
                start_to_close_timeout=RECORD_START_TO_CLOSE,
                schedule_to_close_timeout=RECORD_SCHEDULE_TO_CLOSE,
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            # Started only after the record, because a delivery reads the history row the record writes.
            recorded = {str(outcome.configuration_id) for outcome in chunk}
            started += await start_deliveries(
                [delivery for delivery in evaluation.deliveries if delivery.configuration_id in recorded]
            )
        return started


APPEARANCE_EVALUATION_WORKFLOWS = [AppearanceAlertEvaluateWorkflow]
APPEARANCE_EVALUATION_ACTIVITIES = [evaluate_appearance_alerts_activity]
