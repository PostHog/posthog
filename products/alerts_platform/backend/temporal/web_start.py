"""Sends a delivery from a web request, outside any workflow.

Kept out of the workflow modules, which Temporal loads into its sandbox, because this connects a
client.
"""

from collections.abc import Sequence
from dataclasses import replace

from django.conf import settings

from asgiref.sync import async_to_sync
from temporalio.common import WorkflowIDConflictPolicy

from posthog.exceptions_capture import capture_exception
from posthog.temporal.common.client import async_connect

from products.alerts_platform.backend.delivery.evaluation import deliver_evaluation
from products.alerts_platform.backend.delivery.handoff import deliver_handoff
from products.alerts_platform.backend.delivery.routing import deliver_routes
from products.alerts_platform.backend.facade.contracts import AlertDeliveryRequest
from products.alerts_platform.backend.temporal.workflows import (
    DELIVERY_EXECUTION_TIMEOUT,
    AlertsPlatformDeliverPreviewWorkflow,
    AlertsPlatformHandOverWorkflow,
    delivery_execution_timeout,
    delivery_workflow_id,
    hand_over_workflow_id,
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
        # Routed receivers too, because a routed incident manager otherwise keeps the incident open.
        for send in (deliver_evaluation, deliver_routes):
            try:
                send(replace(delivery, part=part))
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


def start_hand_overs(requests: Sequence[AlertDeliveryRequest]) -> list[AlertDeliveryRequest]:
    """Starts each handoff's workflow over one connection, and returns the ones it could not start, for
    the caller to send inline as far as its budget allows."""
    if not requests:
        return []
    try:
        return async_to_sync(_start_hand_overs)(list(requests))
    except Exception as error:
        capture_exception(error, {"configuration_id": requests[0].configuration_id})
        return list(requests)


def hand_over_inline(request: AlertDeliveryRequest) -> None:
    try:
        deliver_handoff(request)
    except Exception as error:
        capture_exception(error, {"configuration_id": request.configuration_id})


async def _start_hand_overs(requests: list[AlertDeliveryRequest]) -> list[AlertDeliveryRequest]:
    client = await async_connect()
    unstarted: list[AlertDeliveryRequest] = []
    for request in requests:
        try:
            await client.start_workflow(
                AlertsPlatformHandOverWorkflow.run,
                request,
                id=hand_over_workflow_id(request),
                task_queue=settings.ALERTS_PLATFORM_DELIVERY_TASK_QUEUE,
                id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
                execution_timeout=DELIVERY_EXECUTION_TIMEOUT,
            )
        except Exception as error:
            capture_exception(error, {"configuration_id": request.configuration_id})
            unstarted.append(request)
    return unstarted
