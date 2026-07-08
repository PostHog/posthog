import uuid

import pytest
from unittest.mock import patch

import temporalio.worker
from temporalio import activity
from temporalio.client import WorkflowFailureError
from temporalio.exceptions import ApplicationError
from temporalio.testing import ActivityEnvironment, WorkflowEnvironment
from temporalio.worker import Worker

from posthog.temporal.delete_teams.activities import delete_team_records_activity
from posthog.temporal.delete_teams.types import (
    DeleteOrganizationWorkflowInputs,
    DeleteProjectDataWorkflowInputs,
    DeleteTeamsDataWorkflowInputs,
    OrganizationEmailInputs,
    OrganizationRecordInputs,
    ProjectEmailInputs,
    ProjectRecordInputs,
    TeamDataActivityInputs,
)
from posthog.temporal.delete_teams.workflows import (
    DeleteOrganizationWorkflow,
    DeleteProjectDataWorkflow,
    DeleteTeamsDataWorkflow,
)

pytestmark = pytest.mark.asyncio

WORKFLOWS = [DeleteTeamsDataWorkflow, DeleteProjectDataWorkflow, DeleteOrganizationWorkflow]

CORE_ACTIVITY_ORDER = [
    "queue_recording_deletions_activity",
    "delete_misc_small_tables_activity",
    "delete_personless_distinct_ids_activity",
    "delete_cohort_members_activity",
    "delete_groups_activity",
    "delete_team_persons_activity",
    "delete_batch_exports_activity",
    "delete_data_modeling_schedules_activity",
    "delete_team_records_activity",
    "enqueue_clickhouse_deletion_activity",
]


def _recording_activities(calls: list[str]) -> list:
    """Mock every delete_teams activity by name; each records its invocation order."""

    def _team_activity(name: str):
        @activity.defn(name=name)
        async def _fn(inputs: TeamDataActivityInputs) -> None:
            calls.append(name)

        return _fn

    @activity.defn(name="delete_project_record_activity")
    async def delete_project_record_activity(inputs: ProjectRecordInputs) -> None:
        calls.append("delete_project_record_activity")

    @activity.defn(name="delete_organization_record_activity")
    async def delete_organization_record_activity(inputs: OrganizationRecordInputs) -> None:
        calls.append("delete_organization_record_activity")

    @activity.defn(name="send_project_deleted_email_activity")
    async def send_project_deleted_email_activity(inputs: ProjectEmailInputs) -> None:
        calls.append("send_project_deleted_email_activity")

    @activity.defn(name="send_organization_deleted_email_activity")
    async def send_organization_deleted_email_activity(inputs: OrganizationEmailInputs) -> None:
        calls.append("send_organization_deleted_email_activity")

    return [
        *[_team_activity(name) for name in CORE_ACTIVITY_ORDER],
        delete_project_record_activity,
        delete_organization_record_activity,
        send_project_deleted_email_activity,
        send_organization_deleted_email_activity,
    ]


async def _run(workflow, inputs, calls: list[str]) -> None:
    task_queue = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=WORKFLOWS,
            activities=_recording_activities(calls),
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            await env.client.execute_workflow(
                workflow,
                inputs,
                id=str(uuid.uuid4()),
                task_queue=task_queue,
            )


async def test_core_workflow_runs_every_phase_in_order():
    calls: list[str] = []
    await _run(DeleteTeamsDataWorkflow.run, DeleteTeamsDataWorkflowInputs(team_ids=[1, 2], user_id=7), calls)
    assert calls == CORE_ACTIVITY_ORDER


async def test_core_workflow_noop_for_empty_team_ids():
    calls: list[str] = []
    await _run(DeleteTeamsDataWorkflow.run, DeleteTeamsDataWorkflowInputs(team_ids=[], user_id=7), calls)
    assert calls == []


async def test_project_workflow_deletes_record_then_emails():
    calls: list[str] = []
    await _run(
        DeleteProjectDataWorkflow.run,
        DeleteProjectDataWorkflowInputs(team_ids=[1], project_id=42, user_id=7, project_name="proj"),
        calls,
    )
    assert calls == [*CORE_ACTIVITY_ORDER, "delete_project_record_activity", "send_project_deleted_email_activity"]


async def test_environment_only_deletion_skips_project_record():
    calls: list[str] = []
    await _run(
        DeleteProjectDataWorkflow.run,
        DeleteProjectDataWorkflowInputs(team_ids=[1], project_id=None, user_id=7, project_name="env"),
        calls,
    )
    assert "delete_project_record_activity" not in calls
    assert calls == [*CORE_ACTIVITY_ORDER, "send_project_deleted_email_activity"]


async def test_organization_workflow_deletes_record_then_emails():
    calls: list[str] = []
    await _run(
        DeleteOrganizationWorkflow.run,
        DeleteOrganizationWorkflowInputs(
            team_ids=[1, 2],
            organization_id="11111111-1111-1111-1111-111111111111",
            user_id=7,
            organization_name="org",
            project_names=["a", "b"],
        ),
        calls,
    )
    assert calls == [
        *CORE_ACTIVITY_ORDER,
        "delete_organization_record_activity",
        "send_organization_deleted_email_activity",
    ]


def _core_activities_with(target_name: str, target_fn) -> list:
    """Core activity set where target_name uses target_fn and the rest are no-ops."""
    activities = [activity.defn(name=target_name)(target_fn)]
    for name in CORE_ACTIVITY_ORDER:
        if name == target_name:
            continue

        @activity.defn(name=name)
        async def _noop(inputs: TeamDataActivityInputs) -> None:
            pass

        activities.append(_noop)
    return activities


async def _run_core_with(activities: list) -> None:
    task_queue = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=WORKFLOWS,
            activities=activities,
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            await env.client.execute_workflow(
                DeleteTeamsDataWorkflow.run,
                DeleteTeamsDataWorkflowInputs(team_ids=[1], user_id=7),
                id=str(uuid.uuid4()),
                task_queue=task_queue,
            )


async def test_protected_error_fails_fast_without_retry():
    from django.db.models.deletion import ProtectedError

    attempts: list[str] = []

    async def raises_protected(inputs: TeamDataActivityInputs) -> None:
        attempts.append("attempt")
        raise ProtectedError("blocked by a PROTECT foreign key", set())

    activities = _core_activities_with("delete_misc_small_tables_activity", raises_protected)
    with pytest.raises(WorkflowFailureError):
        await _run_core_with(activities)

    assert len(attempts) == 1  # non-retryable: the workflow fails on the first attempt


async def test_transient_error_is_retried():
    attempts: list[str] = []

    async def fails_once(inputs: TeamDataActivityInputs) -> None:
        attempts.append("attempt")
        if len(attempts) == 1:
            raise RuntimeError("transient database hiccup")

    activities = _core_activities_with("delete_misc_small_tables_activity", fails_once)
    await _run_core_with(activities)  # completes despite the first failure

    assert len(attempts) == 2  # retried once, then succeeded


async def test_recording_deletion_failure_does_not_block_workflow():
    # Queuing recording deletion is best-effort: if it exhausts its retries, the rest of the
    # team deletion must still run to completion.
    attempts: list[str] = []

    async def always_fails(inputs: TeamDataActivityInputs) -> None:
        attempts.append("attempt")
        raise RuntimeError("recording deletion service unavailable")

    activities = _core_activities_with("queue_recording_deletions_activity", always_fails)
    await _run_core_with(activities)  # completes despite recording deletion failing

    assert len(attempts) == 5  # exhausted SIDE_EFFECT_RETRY_POLICY, then swallowed


async def test_recursion_error_fails_fast_without_retry():
    # A RecursionError is deterministic (e.g. json.loads can't decode a deeply-nested JSON column
    # on a cascaded row), so the retry policy must not loop on it.
    attempts: list[str] = []

    async def raises_recursion(inputs: TeamDataActivityInputs) -> None:
        attempts.append("attempt")
        raise ApplicationError("recursion limit exceeded", type="RecursionError")

    activities = _core_activities_with("delete_team_records_activity", raises_recursion)
    with pytest.raises(WorkflowFailureError):
        await _run_core_with(activities)

    assert len(attempts) == 1


async def test_delete_team_records_activity_converts_recursion_error():
    # The real activity turns a RecursionError from the cascade into a small, non-retryable
    # ApplicationError so it surfaces instead of looping and overflowing Temporal's failure-size limit.
    def raise_recursion(team_ids: list[int]) -> None:
        raise RecursionError("maximum recursion depth exceeded")

    with patch("posthog.models.team.util.delete_team_records", raise_recursion):
        with pytest.raises(ApplicationError) as exc_info:
            await ActivityEnvironment().run(
                delete_team_records_activity, TeamDataActivityInputs(team_ids=[1], user_id=7)
            )

    assert exc_info.value.type == "RecursionError"
    assert exc_info.value.non_retryable
