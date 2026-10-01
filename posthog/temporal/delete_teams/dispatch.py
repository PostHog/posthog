import asyncio
from datetime import timedelta
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
ORGANIZATION_DELETION_DELAY = timedelta(hours=48)


def project_deletion_delay(project: "Project") -> timedelta | None:
    """How long to wait before the project deletion workflow starts, or None to start it at once.

    The delay is a recovery window for a deletion the user did not mean to request. A project
    where no environment ever ingested an event holds nothing to recover, so it deletes at once.
    """
    return PROJECT_DELETION_DELAY if project.has_ingested_data() else None


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


def cancel_delete_project_data_workflow(*, project_id: int) -> None:
    async def _cancel() -> None:
        client = await async_connect()
        handle = client.get_workflow_handle(f"delete-project-{project_id}")
        await handle.cancel()
        try:
            await handle.result(follow_runs=False)
        except WorkflowFailureError:
            pass

    asyncio.run(_cancel())


def start_delete_organization_workflow(
    *,
    team_ids: list[int],
    organization_id: str,
    user_id: int,
    organization_name: str,
    project_names: list[str],
    start_delay: timedelta | None = None,
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
            start_delay=start_delay,
        )

    asyncio.run(_start())


def cancel_delete_organization_workflow(*, organization_id: str) -> bool:
    """Cancel the organization deletion workflow. Return False when no workflow with that id exists.

    NOT_FOUND means the workflow never started or Temporal has dropped it. Neither case leaves a
    workflow that can still delete the organization.
    """

    async def _cancel() -> bool:
        client = await async_connect()
        handle = client.get_workflow_handle(f"delete-organization-{organization_id}")
        try:
            await handle.cancel()
        except RPCError as error:
            if error.status != RPCStatusCode.NOT_FOUND:
                raise
            return False
        try:
            await handle.result(follow_runs=False)
        except WorkflowFailureError:
            pass
        return True

    return asyncio.run(_cancel())
