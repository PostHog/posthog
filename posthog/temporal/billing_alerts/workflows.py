from __future__ import annotations

import json
import asyncio
import hashlib
import datetime as dt

import temporalio.common
import temporalio.workflow
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.temporal.billing_alerts.activities import (
    discover_due_billing_alerts_activity,
    evaluate_billing_alert_batch_activity,
    notify_billing_alert_events_activity,
)
from posthog.temporal.billing_alerts.retry_policy import (
    BILLING_ALERT_EVALUATE_RETRY_POLICY,
    BILLING_ALERT_NOTIFY_RETRY_POLICY,
)
from posthog.temporal.billing_alerts.types import (
    BillingAlertBatchWorkflowInputs,
    EvaluateBillingAlertBatchActivityInputs,
    NotifyBillingAlertEventsActivityInputs,
)
from posthog.temporal.common.base import PostHogWorkflow

BILLING_ALERT_BATCH_SIZE = 50
BILLING_ALERT_BATCH_EXECUTION_TIMEOUT = dt.timedelta(minutes=70)


def _chunks(items: list[str], size: int) -> list[list[str]]:
    return [items[index : index + size] for index in range(0, len(items), size)]


def _batch_workflow_id(alert_ids: list[str]) -> str:
    digest = hashlib.sha256(",".join(sorted(alert_ids)).encode("utf-8")).hexdigest()[:16]
    return f"check-billing-alert-batch-{digest}"


@temporalio.workflow.defn(name="schedule-due-billing-alert-checks")
class ScheduleDueBillingAlertChecksWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> None:
        return None

    @temporalio.workflow.run
    async def run(self) -> None:
        alerts = await temporalio.workflow.execute_activity(
            discover_due_billing_alerts_activity,
            start_to_close_timeout=dt.timedelta(minutes=2),
            retry_policy=temporalio.common.RetryPolicy(
                initial_interval=dt.timedelta(seconds=5),
                maximum_interval=dt.timedelta(minutes=1),
                maximum_attempts=3,
            ),
        )
        alert_ids = [alert.alert_id for alert in alerts]
        tasks = []
        for batch in _chunks(alert_ids, BILLING_ALERT_BATCH_SIZE):
            tasks.append(
                temporalio.workflow.execute_child_workflow(
                    CheckBillingAlertBatchWorkflow.run,
                    BillingAlertBatchWorkflowInputs(alert_ids=batch),
                    id=_batch_workflow_id(batch),
                    parent_close_policy=temporalio.workflow.ParentClosePolicy.ABANDON,
                    execution_timeout=BILLING_ALERT_BATCH_EXECUTION_TIMEOUT,
                )
            )

        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in results:
                if isinstance(result, WorkflowAlreadyStartedError):
                    temporalio.workflow.logger.info("billing_alert_batch.already_running")
                elif isinstance(result, BaseException):
                    temporalio.workflow.logger.warning(
                        "billing_alert_batch.child_workflow_error",
                        extra={"error": str(result)},
                    )


@temporalio.workflow.defn(name="check-billing-alert-batch")
class CheckBillingAlertBatchWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> BillingAlertBatchWorkflowInputs:
        loaded = BillingAlertBatchWorkflowInputs(**json.loads(inputs[0]))
        if not loaded.alert_ids:
            raise ValueError("alert_ids must not be empty")
        return loaded

    @temporalio.workflow.run
    async def run(self, inputs: BillingAlertBatchWorkflowInputs) -> None:
        event_ids = await temporalio.workflow.execute_activity(
            evaluate_billing_alert_batch_activity,
            EvaluateBillingAlertBatchActivityInputs(alert_ids=inputs.alert_ids),
            start_to_close_timeout=dt.timedelta(minutes=15),
            retry_policy=BILLING_ALERT_EVALUATE_RETRY_POLICY,
        )
        if event_ids:
            await temporalio.workflow.execute_activity(
                notify_billing_alert_events_activity,
                NotifyBillingAlertEventsActivityInputs(event_ids=event_ids),
                start_to_close_timeout=dt.timedelta(minutes=5),
                retry_policy=BILLING_ALERT_NOTIFY_RETRY_POLICY,
            )
