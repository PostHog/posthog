import datetime as dt

from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.dataclasses import frozen
from posthog.temporal.common.base import PostHogWorkflow

with workflow.unsafe.imports_passed_through():
    from django.conf import settings


@frozen
class AlertsProductInputs:
    pass


@activity.defn
async def alerts_product_check_due_activity() -> None:
    pass


@activity.defn
async def alerts_product_deliver_activity() -> None:
    pass


@workflow.defn(name="alerts-product-deliver")
class AlertsProductDeliverWorkflow(PostHogWorkflow):
    inputs_cls = AlertsProductInputs

    @workflow.run
    async def run(self, inputs: AlertsProductInputs) -> None:
        await workflow.execute_activity(
            alerts_product_deliver_activity,
            start_to_close_timeout=dt.timedelta(seconds=10),
            schedule_to_close_timeout=dt.timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )


@workflow.defn(name="alerts-product-check-due")
class AlertsProductCheckDueWorkflow(PostHogWorkflow):
    inputs_cls = AlertsProductInputs

    @workflow.run
    async def run(self, inputs: AlertsProductInputs) -> None:
        await workflow.execute_activity(
            alerts_product_check_due_activity,
            start_to_close_timeout=dt.timedelta(seconds=10),
            schedule_to_close_timeout=dt.timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        # Delivery must outlive the tick, so wait for start confirmation without awaiting the handle.
        await workflow.start_child_workflow(
            AlertsProductDeliverWorkflow.run,
            inputs,
            id=f"alerts-product-deliver-{workflow.info().run_id}",
            task_queue=settings.ALERTS_PRODUCT_DELIVERY_TASK_QUEUE,
            parent_close_policy=workflow.ParentClosePolicy.ABANDON,
            execution_timeout=dt.timedelta(minutes=1),
        )


EVALUATION_WORKFLOWS = [AlertsProductCheckDueWorkflow]
EVALUATION_ACTIVITIES = [alerts_product_check_due_activity]
DELIVERY_WORKFLOWS = [AlertsProductDeliverWorkflow]
DELIVERY_ACTIVITIES = [alerts_product_deliver_activity]
