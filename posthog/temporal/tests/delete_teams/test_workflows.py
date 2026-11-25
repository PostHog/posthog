import uuid
import datetime as dt
import dataclasses
from collections.abc import Callable

import pytest
from unittest.mock import patch

from django.db import OperationalError

import psycopg
import temporalio.worker
from temporalio import activity
from temporalio.client import WorkflowFailureError
from temporalio.exceptions import ApplicationError
from temporalio.testing import ActivityEnvironment, WorkflowEnvironment
from temporalio.worker import Worker

from posthog.temporal.delete_teams.activities import STATEMENT_TIMEOUT_TERMINAL_ATTEMPT, delete_team_records_activity
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
    TASK_UPLOAD_URLS_EXPIRY,
    DeleteOrganizationWorkflow,
    DeleteProjectDataWorkflow,
    DeleteTaskStorageAfterUploadsExpireWorkflow,
    DeleteTeamsDataWorkflow,
)

from products.tasks.backend.facade.api import TASK_RUN_ARTIFACT_UPLOAD_EXPIRATION_SECONDS

pytestmark = pytest.mark.asyncio

WORKFLOWS = [
    DeleteTeamsDataWorkflow,
    DeleteProjectDataWorkflow,
    DeleteOrganizationWorkflow,
    DeleteTaskStorageAfterUploadsExpireWorkflow,
]

TEST_EXECUTION_TIMEOUT = dt.timedelta(hours=6)

CORE_ACTIVITY_ORDER = [
    "queue_recording_deletions_activity",
    "delete_misc_small_tables_activity",
    "delete_cohort_members_activity",
    "delete_groups_activity",
    "delete_team_persons_activity",
    "delete_event_properties_activity",
    "delete_ui_customization_activity",
    "delete_batch_exports_activity",
    "delete_data_modeling_schedules_activity",
    "delete_task_session_storage_activity",
    "delete_team_records_activity",
    "enqueue_clickhouse_deletion_activity",
    "delete_task_storage_activity",
]


def _recording_activities(
    calls: list[str], exclude: frozenset[str] = frozenset(), project_pending: bool = True
) -> list:
    """Mock every delete_teams activity by name; each records its invocation order."""

    def _team_activity(name: str):
        @activity.defn(name=name)
        async def _fn(inputs: TeamDataActivityInputs) -> None:
            calls.append(name)

        return _fn

    @activity.defn(name="deprovision_managed_warehouse_activity")
    async def deprovision_managed_warehouse_activity(inputs: OrganizationRecordInputs) -> None:
        calls.append("deprovision_managed_warehouse_activity")

    @activity.defn(name="check_project_pending_deletion_activity")
    async def check_project_pending_deletion_activity(inputs: ProjectRecordInputs) -> bool:
        calls.append("check_project_pending_deletion_activity")
        return project_pending

    @activity.defn(name="delete_project_record_activity")
    async def delete_project_record_activity(inputs: ProjectRecordInputs) -> None:
        calls.append("delete_project_record_activity")

    @activity.defn(name="delete_organization_record_activity")
    async def delete_organization_record_activity(inputs: OrganizationRecordInputs) -> None:
        calls.append("delete_organization_record_activity")

    @activity.defn(name="delete_organization_task_storage_activity")
    async def delete_organization_task_storage_activity(inputs: OrganizationRecordInputs) -> None:
        calls.append("delete_organization_task_storage_activity")

    @activity.defn(name="send_project_deleted_email_activity")
    async def send_project_deleted_email_activity(inputs: ProjectEmailInputs) -> None:
        calls.append("send_project_deleted_email_activity")

    @activity.defn(name="send_organization_deleted_email_activity")
    async def send_organization_deleted_email_activity(inputs: OrganizationEmailInputs) -> None:
        calls.append("send_organization_deleted_email_activity")

    mocks = [
        *[_team_activity(name) for name in CORE_ACTIVITY_ORDER],
        deprovision_managed_warehouse_activity,
        check_project_pending_deletion_activity,
        delete_project_record_activity,
        delete_organization_record_activity,
        delete_organization_task_storage_activity,
        send_project_deleted_email_activity,
        send_organization_deleted_email_activity,
    ]
    return [fn for fn in mocks if fn.__name__ not in exclude]


async def _run(workflow, inputs, calls: list[str], project_pending: bool = True) -> None:
    task_queue = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=WORKFLOWS,
            activities=_recording_activities(calls, project_pending=project_pending),
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            await env.client.execute_workflow(
                workflow,
                inputs,
                id=str(uuid.uuid4()),
                task_queue=task_queue,
                execution_timeout=TEST_EXECUTION_TIMEOUT,
            )


async def test_core_workflow_runs_every_phase_in_order():
    calls: list[str] = []
    await _run(DeleteTeamsDataWorkflow.run, DeleteTeamsDataWorkflowInputs(team_ids=[1, 2], user_id=7), calls)
    assert calls == CORE_ACTIVITY_ORDER


async def test_core_workflow_leaves_a_storage_resweep_running_after_it_completes():
    calls: list[str] = []
    task_queue = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=WORKFLOWS,
            activities=_recording_activities(calls),
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            workflow_id = str(uuid.uuid4())
            handle = await env.client.start_workflow(
                DeleteTeamsDataWorkflow.run,
                DeleteTeamsDataWorkflowInputs(team_ids=[1], user_id=7),
                id=workflow_id,
                task_queue=task_queue,
                execution_timeout=TEST_EXECUTION_TIMEOUT,
            )
            await handle.result()
            resweep = await env.client.get_workflow_handle(
                f"{workflow_id}-{handle.result_run_id}-task-storage-after-uploads-expire"
            ).describe()

    assert resweep.workflow_type == "delete-task-storage-after-uploads-expire"


async def test_storage_resweep_deletes_team_storage_after_waiting():
    calls: list[str] = []
    await _run(DeleteTaskStorageAfterUploadsExpireWorkflow.run, TeamDataActivityInputs(team_ids=[1], user_id=7), calls)
    assert calls == ["delete_task_storage_activity"]


def test_the_storage_resweep_waits_out_every_task_upload_url():
    assert TASK_UPLOAD_URLS_EXPIRY.total_seconds() > TASK_RUN_ARTIFACT_UPLOAD_EXPIRATION_SECONDS


async def test_core_workflow_noop_for_empty_team_ids():
    calls: list[str] = []
    await _run(DeleteTeamsDataWorkflow.run, DeleteTeamsDataWorkflowInputs(team_ids=[], user_id=7), calls)
    assert calls == []


async def test_core_workflow_replays_history_without_customization_cleanup():
    calls: list[str] = []
    task_queue = str(uuid.uuid4())
    patched = temporalio.workflow.patched
    async with await WorkflowEnvironment.start_time_skipping() as env:
        with patch(
            "temporalio.workflow.patched",
            side_effect=lambda name: False if name == "delete-ui-customization" else patched(name),
        ):
            async with Worker(
                env.client,
                task_queue=task_queue,
                workflows=WORKFLOWS,
                activities=_recording_activities(calls),
                workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
            ):
                handle = await env.client.start_workflow(
                    DeleteTeamsDataWorkflow.run,
                    DeleteTeamsDataWorkflowInputs(team_ids=[1], user_id=7),
                    id=str(uuid.uuid4()),
                    task_queue=task_queue,
                    execution_timeout=dt.timedelta(minutes=2),
                )
                await handle.result()
                history = await handle.fetch_history()

    assert calls == [name for name in CORE_ACTIVITY_ORDER if name != "delete_ui_customization_activity"]
    await temporalio.worker.Replayer(
        workflows=WORKFLOWS, workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner()
    ).replay_workflow(history)


async def test_project_workflow_deletes_record_then_emails():
    calls: list[str] = []
    await _run(
        DeleteProjectDataWorkflow.run,
        DeleteProjectDataWorkflowInputs(team_ids=[1], project_id=42, user_id=7, project_name="proj"),
        calls,
    )
    assert calls == [
        "check_project_pending_deletion_activity",
        *CORE_ACTIVITY_ORDER,
        "delete_project_record_activity",
        "send_project_deleted_email_activity",
    ]


async def test_project_workflow_stops_when_project_is_not_pending_deletion():
    calls: list[str] = []
    await _run(
        DeleteProjectDataWorkflow.run,
        DeleteProjectDataWorkflowInputs(team_ids=[1], project_id=42, user_id=7, project_name="proj"),
        calls,
        project_pending=False,
    )
    assert calls == ["check_project_pending_deletion_activity"]


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
        "deprovision_managed_warehouse_activity",
        *(name for name in CORE_ACTIVITY_ORDER if name != "delete_task_session_storage_activity"),
        "delete_organization_record_activity",
        "delete_organization_task_storage_activity",
        "send_organization_deleted_email_activity",
    ]


def _core_activities_with(target_name: str, target_fn) -> list:
    """Core activity set where target_name uses target_fn and the rest are no-ops."""
    activities = [activity.defn(name=target_name)(target_fn)]
    for name in CORE_ACTIVITY_ORDER:
        if name == target_name:
            continue

        activities.append(_noop_team_activity(name))
    return activities


def _noop_team_activity(name: str):
    @activity.defn(name=name)
    async def _noop(inputs: TeamDataActivityInputs) -> None:
        pass

    return _noop


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
                execution_timeout=TEST_EXECUTION_TIMEOUT,
            )


@pytest.mark.parametrize("activity_name", ["delete_misc_small_tables_activity", "delete_ui_customization_activity"])
async def test_protected_error_fails_fast_without_retry(activity_name: str):
    from django.db.models.deletion import ProtectedError

    attempts: list[str] = []

    async def raises_protected(inputs: TeamDataActivityInputs) -> None:
        attempts.append("attempt")
        raise ProtectedError("blocked by a PROTECT foreign key", set())

    activities = _core_activities_with(activity_name, raises_protected)
    with pytest.raises(WorkflowFailureError):
        await _run_core_with(activities)

    assert len(attempts) == 1  # non-retryable: the workflow fails on the first attempt


@pytest.mark.parametrize(
    "activity_name",
    ["delete_misc_small_tables_activity", "delete_ui_customization_activity", "delete_task_storage_activity"],
)
async def test_transient_error_is_retried(activity_name: str):
    attempts: list[str] = []

    async def fails_once(inputs: TeamDataActivityInputs) -> None:
        attempts.append("attempt")
        if len(attempts) == 1:
            raise RuntimeError("transient database hiccup")

    activities = _core_activities_with(activity_name, fails_once)
    await _run_core_with(activities)  # completes despite the first failure

    assert len(attempts) == 2  # retried once, then succeeded


async def test_warehouse_deprovision_failure_blocks_org_record_deletion():
    # The rest of the org deletion is conditional on duckgres accepting the deprovision: the
    # org-record cascade destroys the DuckgresServer pointer, so a persistent control-plane
    # outage must stall the workflow (the activity keeps retrying) rather than orphan a live
    # warehouse with no pointer left. The execution timeout is test-only, to bound the
    # otherwise-indefinite retries.
    attempts: list[str] = []
    calls: list[str] = []

    @activity.defn(name="deprovision_managed_warehouse_activity")
    async def failing_deprovision(inputs: OrganizationRecordInputs) -> None:
        attempts.append("attempt")
        raise RuntimeError("duckgres control plane unavailable")

    activities = [
        *_recording_activities(calls, exclude=frozenset({"deprovision_managed_warehouse_activity"})),
        failing_deprovision,
    ]
    task_queue = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=WORKFLOWS,
            activities=activities,
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            with pytest.raises(WorkflowFailureError):
                await env.client.execute_workflow(
                    DeleteOrganizationWorkflow.run,
                    DeleteOrganizationWorkflowInputs(
                        team_ids=[1],
                        organization_id="11111111-1111-1111-1111-111111111111",
                        user_id=7,
                        organization_name="org",
                        project_names=["a"],
                    ),
                    id=str(uuid.uuid4()),
                    task_queue=task_queue,
                    execution_timeout=dt.timedelta(hours=1),
                )

    assert len(attempts) > 1  # durably retried until the test-only execution timeout
    assert calls == []  # nothing else ran — the pointer-destroying cascade never started


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


def _database_error(cause: Exception) -> OperationalError:
    error = OperationalError(str(cause))
    error.__cause__ = cause
    return error


def _activity_environment(attempt: int) -> ActivityEnvironment:
    environment = ActivityEnvironment()
    environment.info = dataclasses.replace(environment.info, attempt=attempt)
    return environment


@pytest.mark.parametrize(
    "error,attempt,error_type",
    [
        (RecursionError("maximum recursion depth exceeded"), 1, "RecursionError"),
        (
            _database_error(psycopg.errors.QueryCanceled("canceling statement due to statement timeout")),
            STATEMENT_TIMEOUT_TERMINAL_ATTEMPT,
            "StatementTimeout",
        ),
    ],
)
async def test_delete_team_records_activity_fails_a_futile_retry_terminally(
    error: Exception, attempt: int, error_type: str
):
    # The real activity turns an error that every retry repeats into a small, non-retryable
    # ApplicationError so it surfaces instead of looping and overflowing Temporal's failure-size limit.
    def raise_error(team_ids: list[int], should_stop: Callable[[], bool] | None = None) -> None:
        raise error

    with patch("posthog.models.team.util.delete_team_records", raise_error):
        with pytest.raises(ApplicationError) as exc_info:
            await _activity_environment(attempt).run(
                delete_team_records_activity, TeamDataActivityInputs(team_ids=[1], user_id=7)
            )

    assert exc_info.value.type == error_type
    assert exc_info.value.non_retryable


@pytest.mark.parametrize(
    "cause,attempt",
    [
        (
            psycopg.errors.LockNotAvailable("canceling statement due to lock timeout"),
            STATEMENT_TIMEOUT_TERMINAL_ATTEMPT,
        ),
        (psycopg.errors.QueryCanceled("canceling statement due to user request"), STATEMENT_TIMEOUT_TERMINAL_ATTEMPT),
        (psycopg.errors.QueryCanceled("canceling statement due to statement timeout"), 1),
    ],
)
async def test_delete_team_records_activity_retries_an_error_that_a_retry_can_pass(cause: Exception, attempt: int):
    def raise_error(team_ids: list[int], should_stop: Callable[[], bool] | None = None) -> None:
        raise _database_error(cause)

    with patch("posthog.models.team.util.delete_team_records", raise_error):
        with pytest.raises(OperationalError):
            await _activity_environment(attempt).run(
                delete_team_records_activity, TeamDataActivityInputs(team_ids=[1], user_id=7)
            )
