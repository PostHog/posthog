import asyncio
from datetime import timedelta
from enum import StrEnum
from typing import TYPE_CHECKING

from django.conf import settings

from temporalio.client import WorkflowFailureError
from temporalio.common import WorkflowIDConflictPolicy
from temporalio.service import RPCError, RPCStatusCode

from posthog.temporal.common.client import async_connect
from posthog.temporal.delete_teams.types import DeleteOrganizationWorkflowInputs, DeleteProjectDataWorkflowInputs

if TYPE_CHECKING:
    from posthog.models.project import Project

PROJECT_DELETION_DELAY = timedelta(hours=48)
PROJECT_DELETION_DELAY_WITHOUT_DATA = timedelta(hours=1)


class ProjectDeletionCancellation(StrEnum):
    """Why the scheduled deletion is off. Both values mean the project keeps its data."""

    CANCELED = "canceled"
    WORKFLOW_NOT_RUNNING = "workflow_not_running"


def project_deletion_delay(project: "Project") -> timedelta:
    """How long to wait before the project deletion workflow starts.

    The delay is a recovery window for a deletion the user did not mean to request. A project
    where no environment ever ingested an event holds no events to recover, but it still holds
    the configuration the user built, so its window is short rather than absent.
    """
    return PROJECT_DELETION_DELAY if project.has_ingested_data() else PROJECT_DELETION_DELAY_WITHOUT_DATA


def start_delete_project_data_workflow(
    *,
    team_ids: list[int],
    project_id: int | None,
    user_id: int,
    project_name: str,
    start_delay: timedelta | None = None,
    id_conflict_policy: WorkflowIDConflictPolicy = WorkflowIDConflictPolicy.UNSPECIFIED,
) -> None:
    inputs = DeleteProjectDataWorkflowInputs(
        team_ids=team_ids, project_id=project_id, user_id=user_id, project_name=project_name
    )
    workflow_id = f"delete-project-{project_id}" if project_id is not None else f"delete-environment-{team_ids[0]}"

    async def _start() -> None:
        client = await async_connect()
        await client.start_workflow(
            "delete-project-data",
            inputs,
            id=workflow_id,
            task_queue=settings.GENERAL_PURPOSE_TASK_QUEUE,
            start_delay=start_delay if project_id is not None else None,
            id_conflict_policy=id_conflict_policy,
        )

    asyncio.run(_start())


def cancel_delete_project_data_workflow(*, project_id: int) -> ProjectDeletionCancellation:
    async def _cancel() -> ProjectDeletionCancellation:
        client = await async_connect()
        handle = client.get_workflow_handle(f"delete-project-{project_id}")
        try:
            await handle.cancel()
        except RPCError as error:
            # NOT_FOUND covers "never started" and "already closed". Neither leaves a workflow
            # that can still delete the project, so the deletion is off in both cases.
            if error.status != RPCStatusCode.NOT_FOUND:
                raise
            return ProjectDeletionCancellation.WORKFLOW_NOT_RUNNING
        try:
            await handle.result(follow_runs=False)
        except WorkflowFailureError:
            pass
        return ProjectDeletionCancellation.CANCELED

    return asyncio.run(_cancel())


def start_delete_organization_workflow(
    *, team_ids: list[int], organization_id: str, user_id: int, organization_name: str, project_names: list[str]
) -> None:
    inputs = DeleteOrganizationWorkflowInputs(
        team_ids=team_ids,
        organization_id=organization_id,
        user_id=user_id,
        organization_name=organization_name,
        project_names=project_names,
    )

    async def _start() -> None:
        client = await async_connect()
        await client.start_workflow(
            "delete-organization",
            inputs,
            id=f"delete-organization-{organization_id}",
            task_queue=settings.GENERAL_PURPOSE_TASK_QUEUE,
        )

    asyncio.run(_start())
