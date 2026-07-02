"""Helpers to start Zendesk import Temporal workflows."""

from __future__ import annotations

from django.conf import settings

from temporalio.common import WorkflowIDReusePolicy

from posthog.temporal.common.client import async_connect

from products.conversations.backend.temporal.zendesk_import.constants import WORKFLOW_ID_PREFIX
from products.conversations.backend.temporal.zendesk_import.workflows import (
    ZendeskImportCoordinatorInput,
    ZendeskImportCoordinatorWorkflow,
)


async def start_zendesk_import_workflow(
    *,
    job_id: str,
    team_id: int,
    dry_run: bool = False,
    max_tickets: int | None = None,
    default_email_channel_id: str | None = None,
) -> tuple[str, str | None]:
    client = await async_connect()
    workflow_id = f"{WORKFLOW_ID_PREFIX}-{team_id}-{job_id}"
    handle = await client.start_workflow(
        ZendeskImportCoordinatorWorkflow.run,
        ZendeskImportCoordinatorInput(
            job_id=job_id,
            team_id=team_id,
            dry_run=dry_run,
            max_tickets=max_tickets,
            default_email_channel_id=default_email_channel_id,
        ),
        id=workflow_id,
        task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
        id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
    )
    return workflow_id, handle.run_id
