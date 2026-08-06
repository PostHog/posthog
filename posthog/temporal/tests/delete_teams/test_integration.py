import uuid

import pytest

import temporalio.worker
from asgiref.sync import sync_to_async
from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from posthog.models.async_deletion import AsyncDeletion, DeletionType
from posthog.models.organization import Organization
from posthog.models.team import Team
from posthog.temporal.delete_teams import ACTIVITIES as REAL_ACTIVITIES
from posthog.temporal.delete_teams.types import (
    DeleteOrganizationWorkflowInputs,
    OrganizationEmailInputs,
    ProjectEmailInputs,
    TeamDataActivityInputs,
)
from posthog.temporal.delete_teams.workflows import (
    DeleteOrganizationWorkflow,
    DeleteProjectDataWorkflow,
    DeleteTeamsDataWorkflow,
)

from products.early_access_features.backend.models import EarlyAccessFeature

pytestmark = [pytest.mark.asyncio, pytest.mark.django_db(transaction=True)]

WORKFLOWS = [DeleteTeamsDataWorkflow, DeleteProjectDataWorkflow, DeleteOrganizationWorkflow]

# Activities that reach out to Temporal schedules / email are stubbed so the test stays
# hermetic; every Postgres-deletion activity runs for real against the test DB.
STUBBED_ACTIVITY_NAMES = {
    "queue_recording_deletions_activity",
    "delete_batch_exports_activity",
    "delete_data_modeling_schedules_activity",
    "send_organization_deleted_email_activity",
    "send_project_deleted_email_activity",
}


def _activities_with_stubs() -> list:
    @activity.defn(name="queue_recording_deletions_activity")
    async def queue_recording_deletions_activity(inputs: TeamDataActivityInputs) -> None:
        pass

    @activity.defn(name="delete_batch_exports_activity")
    async def delete_batch_exports_activity(inputs: TeamDataActivityInputs) -> None:
        pass

    @activity.defn(name="delete_data_modeling_schedules_activity")
    async def delete_data_modeling_schedules_activity(inputs: TeamDataActivityInputs) -> None:
        pass

    @activity.defn(name="send_organization_deleted_email_activity")
    async def send_organization_deleted_email_activity(inputs: OrganizationEmailInputs) -> None:
        pass

    @activity.defn(name="send_project_deleted_email_activity")
    async def send_project_deleted_email_activity(inputs: ProjectEmailInputs) -> None:
        pass

    real = [fn for fn in REAL_ACTIVITIES if fn.__name__ not in STUBBED_ACTIVITY_NAMES]
    return [
        *real,
        queue_recording_deletions_activity,
        delete_batch_exports_activity,
        delete_data_modeling_schedules_activity,
        send_organization_deleted_email_activity,
        send_project_deleted_email_activity,
    ]


def _bootstrap_tenant() -> tuple[str, int]:
    org, _, team = Organization.objects.bootstrap(None)
    EarlyAccessFeature.objects.create(team=team, name="to-be-deleted", stage="concept")
    return str(org.id), team.id


def _tenant_state(org_id: str, team_id: int) -> dict[str, bool]:
    return {
        "org": Organization.objects.filter(id=org_id).exists(),
        "team": Team.objects.filter(id=team_id).exists(),
        "early_access_feature": EarlyAccessFeature.objects.filter(team_id=team_id).exists(),
        "async_deletion": AsyncDeletion.objects.filter(deletion_type=DeletionType.Team, team_id=team_id).exists(),
    }


async def _execute(workflow, inputs) -> None:
    task_queue = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=WORKFLOWS,
            activities=_activities_with_stubs(),
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            await env.client.execute_workflow(workflow, inputs, id=str(uuid.uuid4()), task_queue=task_queue)


async def test_organization_workflow_deletes_real_rows():
    org_id, team_id = await sync_to_async(_bootstrap_tenant)()

    before = await sync_to_async(_tenant_state)(org_id, team_id)
    assert before == {"org": True, "team": True, "early_access_feature": True, "async_deletion": False}

    await _execute(
        DeleteOrganizationWorkflow.run,
        DeleteOrganizationWorkflowInputs(
            team_ids=[team_id],
            organization_id=org_id,
            user_id=999999,  # no such user; report + email paths no-op safely
            organization_name="throwaway",
            project_names=[],
        ),
    )

    after = await sync_to_async(_tenant_state)(org_id, team_id)
    assert after == {"org": False, "team": False, "early_access_feature": False, "async_deletion": True}
