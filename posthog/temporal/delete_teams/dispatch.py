import asyncio

from django.conf import settings

from posthog.temporal.common.client import async_connect
from posthog.temporal.delete_teams.types import DeleteOrganizationWorkflowInputs, DeleteProjectDataWorkflowInputs


def start_delete_project_data_workflow(
    *, team_ids: list[int], project_id: int | None, user_id: int, project_name: str
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
        )

    asyncio.run(_start())


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
