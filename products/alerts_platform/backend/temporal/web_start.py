"""Sends a delivery from a web request, outside any workflow.

Kept out of the workflow modules, which Temporal loads into its sandbox, because this connects a
client.
"""

from dataclasses import replace

from django.conf import settings

from asgiref.sync import async_to_sync
from temporalio.common import WorkflowIDConflictPolicy

from posthog.exceptions_capture import capture_exception
from posthog.temporal.common.client import async_connect

from products.alerts_platform.backend.delivery.evaluation import deliver_evaluation
from products.alerts_platform.backend.facade.contracts import AlertDeliveryRequest
from products.alerts_platform.backend.temporal.workflows import (
    AlertsPlatformDeliverPreviewWorkflow,
    delivery_execution_timeout,
    delivery_workflow_id,
)


def deliver(delivery: AlertDeliveryRequest) -> None:
    """Starts the delivery workflow, so the delivery gets its retries and its wait on a busy thread.

    Sends inline when Temporal cannot be reached, because a caller that ends a firing is the only one
    that will ever send its resolve.
    """
    try:
        async_to_sync(_start)(delivery)
    except Exception as error:
        capture_exception(error, {"configuration_id": delivery.configuration_id})
        deliver_inline(delivery)


def deliver_inline(delivery: AlertDeliveryRequest) -> None:
    """Sends every part before returning, for a caller about to remove the destinations."""
    for part in range(delivery.parts):
        try:
            deliver_evaluation(replace(delivery, part=part))
        except Exception as error:
            # The caller's change goes ahead. A send that failed leaves the incident open, which
            # error tracking shows.
            capture_exception(error, {"configuration_id": delivery.configuration_id})


async def _start(delivery: AlertDeliveryRequest) -> None:
    client = await async_connect()
    await client.start_workflow(
        AlertsPlatformDeliverPreviewWorkflow.run,
        delivery,
        id=delivery_workflow_id(delivery),
        task_queue=settings.ALERTS_PLATFORM_DELIVERY_TASK_QUEUE,
        id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
        execution_timeout=delivery_execution_timeout(delivery),
    )
