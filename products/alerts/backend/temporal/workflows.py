import datetime as dt

from temporalio import activity, workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import (
    ActivityError,
    ApplicationError,
    TimeoutError,
    TimeoutType,
    WorkflowAlreadyStartedError,
)

from posthog.dataclasses import frozen
from posthog.temporal.common.base import PostHogWorkflow

with workflow.unsafe.imports_passed_through():
    from django.conf import settings
    from django.db import InterfaceError, OperationalError

    from asgiref.sync import sync_to_async

    from posthog.temporal.common.logger import get_write_only_logger

    from products.alerts.backend.facade.contracts import AlertDeliveryPreview, SourceCycleInputs
    from products.alerts.backend.temporal.postgres import check_postgres_connection
    from products.alerts.backend.temporal.sources import source_cycle_bindings


POSTGRES_PROBE_FAILURE = "AlertsProductPostgresProbeFailure"

LOGGER = get_write_only_logger(__name__)


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


@workflow.defn(name="alerts-product-source-tick")
class AlertsProductSourceTickWorkflow(PostHogWorkflow):
    """Starts one evaluation cycle per source, then returns without waiting for them.

    The tick holds no source knowledge. It starts each cycle by workflow name taken from
    the binding registry, so a source stays out of the orchestrator's import graph and
    adding one does not change this workflow.
    """

    inputs_cls = AlertsProductInputs

    @workflow.run
    async def run(self, inputs: AlertsProductInputs) -> None:
        # Floored to the minute so the id names the tick occasion rather than the instant.
        # A retried start for the same occasion then collides instead of running twice.
        tick_started_at = workflow.now().replace(second=0, microsecond=0).isoformat()

        for binding in source_cycle_bindings():
            try:
                await workflow.start_child_workflow(
                    binding.workflow_name,
                    SourceCycleInputs(source_kind=binding.source_kind),
                    id=f"alerts-cycle-{binding.source_kind}-{tick_started_at}",
                    task_queue=binding.task_queue,
                    parent_close_policy=workflow.ParentClosePolicy.ABANDON,
                    execution_timeout=dt.timedelta(minutes=5),
                )
            except WorkflowAlreadyStartedError:
                workflow.logger.info(
                    "Source cycle for this tick is already running",
                    extra={"source_kind": binding.source_kind, "tick_started_at": tick_started_at},
                )


@activity.defn
async def alerts_product_deliver_preview_activity(preview: AlertDeliveryPreview) -> None:
    """Records what a delivery would send. It contacts no destination.

    The production fleet for each source still delivers these alerts, so a second real
    send here would notify a person twice for one breach.
    """
    await LOGGER.ainfo(
        "alerts_product_delivery_preview",
        source_kind=preview.source_kind,
        alert_id=preview.alert_id,
        alert_name=preview.alert_name,
        notification=preview.notification,
        destination_names=list(preview.destination_names),
        evaluation_key=preview.evaluation_key,
    )


@workflow.defn(name="alerts-product-deliver-preview")
class AlertsProductDeliverPreviewWorkflow(PostHogWorkflow):
    inputs_cls = AlertDeliveryPreview

    @workflow.run
    async def run(self, inputs: AlertDeliveryPreview) -> None:
        await workflow.execute_activity(
            alerts_product_deliver_preview_activity,
            inputs,
            start_to_close_timeout=dt.timedelta(seconds=10),
            schedule_to_close_timeout=dt.timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )


# The tick belongs on the orchestration queue. It registers here until that queue reaches
# master, so the evaluation fleet runs it in the meantime.
EVALUATION_WORKFLOWS = [AlertsProductCheckDueWorkflow, AlertsProductSourceTickWorkflow]
EVALUATION_ACTIVITIES = [alerts_product_check_due_activity]
DELIVERY_WORKFLOWS = [AlertsProductDeliverWorkflow, AlertsProductDeliverPreviewWorkflow]
DELIVERY_ACTIVITIES = [alerts_product_deliver_activity, alerts_product_deliver_preview_activity]
