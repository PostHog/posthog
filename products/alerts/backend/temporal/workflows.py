import datetime as dt

from temporalio import activity, workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, ApplicationError, TimeoutError, TimeoutType

from posthog.dataclasses import frozen
from posthog.temporal.common.base import PostHogWorkflow

with workflow.unsafe.imports_passed_through():
    from django.conf import settings
    from django.db import InterfaceError, OperationalError

    from asgiref.sync import sync_to_async

    from products.alerts.backend.temporal.postgres import check_postgres_connection


POSTGRES_PROBE_FAILURE = "AlertsProductPostgresProbeFailure"


@frozen
class AlertsProductInputs:
    pass


@activity.defn
async def alerts_product_check_due_activity() -> None:
    try:
        await sync_to_async(check_postgres_connection, thread_sensitive=False)()
    except (OperationalError, InterfaceError):
        raise ApplicationError("Postgres connectivity probe failed", type=POSTGRES_PROBE_FAILURE) from None


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
        try:
            await workflow.execute_activity(
                alerts_product_check_due_activity,
                start_to_close_timeout=dt.timedelta(seconds=10),
                schedule_to_close_timeout=dt.timedelta(seconds=30),
                retry_policy=RetryPolicy(maximum_attempts=1),
            )
        except ActivityError as error:
            if isinstance(error.cause, ApplicationError) and error.cause.type == POSTGRES_PROBE_FAILURE:
                pass
            elif isinstance(error.cause, TimeoutError) and error.cause.type in (
                TimeoutType.START_TO_CLOSE,
                TimeoutType.SCHEDULE_TO_CLOSE,
            ):
                workflow.logger.warning("Postgres probe timed out; database outcome unknown; delivery is continuing")
            else:
                raise
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
