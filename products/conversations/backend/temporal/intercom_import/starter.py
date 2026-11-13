"""Helpers to start Intercom import Temporal workflows."""

from __future__ import annotations

from django.conf import settings

from temporalio.common import WorkflowIDReusePolicy
from temporalio.service import RPCError, RPCStatusCode

from posthog.temporal.common.client import async_connect

from products.conversations.backend.temporal.intercom_import.constants import WORKFLOW_ID_PREFIX
from products.conversations.backend.temporal.intercom_import.workflows import (
    IntercomImportCoordinatorInput,
    IntercomImportCoordinatorWorkflow,
)


def coordinator_workflow_id(*, team_id: int, job_id: str) -> str:
    return f"{WORKFLOW_ID_PREFIX}-{team_id}-{job_id}"


async def intercom_import_workflow_exists(*, team_id: int, job_id: str) -> bool:
    """Whether Temporal has a workflow for this job, reading anything but a clean not-found as yes.

    Releasing a live job lets a second import start against it, which is worse than leaving a dead
    job blocked a while longer. A namespace that does not resolve answers NOT_FOUND for every
    workflow, so that case also counts as "exists".
    """
    try:
        client = await async_connect()
        await client.get_workflow_handle(coordinator_workflow_id(team_id=team_id, job_id=job_id)).describe()
        return True
    except RPCError as error:
        return error.status != RPCStatusCode.NOT_FOUND or "namespace" in error.message.lower()
    except Exception:
        return True


async def start_intercom_import_workflow(
    *,
    job_id: str,
    team_id: int,
    default_email_channel_id: str | None = None,
) -> tuple[str, str | None]:
    client = await async_connect()
    workflow_id = coordinator_workflow_id(team_id=team_id, job_id=job_id)
    task_queue = settings.VIDEO_EXPORT_TASK_QUEUE
    handle = await client.start_workflow(
        IntercomImportCoordinatorWorkflow.run,
        IntercomImportCoordinatorInput(
            job_id=job_id,
            team_id=team_id,
            default_email_channel_id=default_email_channel_id,
            task_queue=task_queue,
        ),
        id=workflow_id,
        task_queue=task_queue,
        id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
    )
    return workflow_id, handle.run_id
