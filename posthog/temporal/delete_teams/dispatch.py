import asyncio

from django.conf import settings

import posthoganalytics

from posthog.temporal.common.client import async_connect
from posthog.temporal.delete_teams.types import DeleteOrganizationWorkflowInputs, DeleteProjectDataWorkflowInputs

TEMPORAL_DELETION_ROLLOUT_FLAG = "temporal-deletion-rollout"


def delete_via_temporal_enabled(organization_id: str) -> bool:
    """Whether org/project/team deletion for this organization should run on Temporal.

    Evaluated at the API dispatch site so the rollout can be ramped per organization.
    Returns False when flags are unavailable (e.g. self-hosted), keeping deletion on Celery.
    """
    return bool(
        posthoganalytics.feature_enabled(
            TEMPORAL_DELETION_ROLLOUT_FLAG,
            organization_id,
            groups={"organization": organization_id},
            group_properties={"organization": {"id": organization_id}},
        )
    )


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
