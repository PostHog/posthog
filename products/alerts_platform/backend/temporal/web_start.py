"""Starts platform workflows from a web request, outside any workflow.

Kept out of the workflow modules, which Temporal loads into its sandbox, because this connects a
client.
"""

from django.conf import settings

from asgiref.sync import async_to_sync
from temporalio.common import WorkflowIDConflictPolicy

from posthog.temporal.common.client import async_connect

from products.alerts_platform.backend.facade.contracts import AlertDeliveryRequest
from products.alerts_platform.backend.temporal.workflows import (
    DELIVERY_EXECUTION_TIMEOUT,
    AlertsPlatformDeliverPreviewWorkflow,
)


def start_delivery(delivery: AlertDeliveryRequest) -> None:
    """Starts one delivery workflow, such as the close an edit owes an incident.

    The workflow and id shape a source's evaluation uses, so the delivery gets the same retries and
    the same wait on a busy thread. A delivery already running under the id is left to run.
    """
    async_to_sync(_start_delivery)(delivery)


async def _start_delivery(delivery: AlertDeliveryRequest) -> None:
    client = await async_connect()
    await client.start_workflow(
        AlertsPlatformDeliverPreviewWorkflow.run,
        delivery,
        id=f"alerts-deliver-preview-{delivery.configuration_id}:{delivery.evaluation_key}",
        task_queue=settings.ALERTS_PLATFORM_DELIVERY_TASK_QUEUE,
        id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
        execution_timeout=DELIVERY_EXECUTION_TIMEOUT * max(1, delivery.parts),
    )
