import uuid
import dataclasses
from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from django.conf import settings
from django.test import SimpleTestCase

import pytest_asyncio
from parameterized import parameterized
from temporalio import activity
from temporalio.client import ScheduleOverlapPolicy, WorkflowFailureError
from temporalio.testing import ActivityEnvironment, WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from products.cloud_agents.backend.facade import temporal as temporal_facade
from products.cloud_agents.backend.logic import sweeps
from products.cloud_agents.backend.logic.status import QUOTA_SWEEP_CANCEL_SOURCE
from products.cloud_agents.backend.temporal.activities import (
    StopRunsOverQuotaInputs,
    StopRunsOverQuotaResult,
    stop_cloud_agent_runs_over_quota_activity,
)
from products.cloud_agents.backend.temporal.schedule import INTERVAL, SCHEDULE_ID
from products.cloud_agents.backend.temporal.workflows import WORKFLOW_NAME, StopCloudAgentRunsOverQuotaWorkflow
from products.tasks.backend.facade.contracts import CloudAgentActiveRunDTO

SWEEPS = "products.cloud_agents.backend.logic.sweeps"


def _active_runs(count: int) -> list[CloudAgentActiveRunDTO]:
    return [CloudAgentActiveRunDTO(task_id=uuid.uuid4(), task_run_id=uuid.uuid4()) for _ in range(count)]


class TestStopRunsOverQuota(SimpleTestCase):
    def sweep(
        self, active_by_team: dict[int, list[CloudAgentActiveRunDTO]], cancel: Any, **kwargs: Any
    ) -> tuple[int, MagicMock, MagicMock]:
        def list_active(*, team_id: int, limit: int) -> list[CloudAgentActiveRunDTO]:
            return active_by_team[team_id][:limit]

        with (
            patch(f"{SWEEPS}.list_teams_over_cloud_agents_quota_with_active_runs", return_value=list(active_by_team)),
            patch(f"{SWEEPS}.list_active_billable_cloud_agent_runs", side_effect=list_active) as list_runs,
            patch(f"{SWEEPS}.cancel_task_run", side_effect=cancel) as cancel_task_run,
        ):
            return sweeps.stop_runs_over_quota(**kwargs), list_runs, cancel_task_run

    def test_each_active_run_of_a_team_over_its_limit_is_cancelled_with_the_sweep_as_its_source(self) -> None:
        active = {7: _active_runs(2), 9: _active_runs(1)}

        cancelled, _, cancel_task_run = self.sweep(active, lambda *args, **kwargs: ("accepted", None))

        assert cancelled == 3
        assert [call.args for call in cancel_task_run.call_args_list] == [
            (run.task_run_id, run.task_id, team_id) for team_id, runs in active.items() for run in runs
        ]
        # The public stop reason of the run is read back from this source.
        assert {call.kwargs["source"] for call in cancel_task_run.call_args_list} == {QUOTA_SWEEP_CANCEL_SOURCE}
        assert {call.kwargs["reason"] for call in cancel_task_run.call_args_list} == {sweeps.USAGE_LIMIT_CANCEL_REASON}

    @parameterized.expand(
        [
            ("already_ended", ("already_terminal", None)),
            ("tasks_cannot_cancel_now", ("unavailable", None)),
            ("cancel_raises", RuntimeError("Temporal is down")),
        ]
    )
    def test_run_that_is_not_cancelled_does_not_stop_the_sweep(self, _name: str, first_outcome: Any) -> None:
        outcomes = iter([first_outcome, ("accepted", None), ("accepted", None)])

        def cancel(*args: Any, **kwargs: Any) -> Any:
            outcome = next(outcomes)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        cancelled, _, cancel_task_run = self.sweep({7: _active_runs(2), 9: _active_runs(1)}, cancel)

        assert (cancelled, cancel_task_run.call_count) == (2, 3)

    def test_one_sweep_cancels_no_more_runs_than_its_batch_size(self) -> None:
        cancelled, list_runs, cancel_task_run = self.sweep(
            {7: _active_runs(3), 9: _active_runs(3), 11: _active_runs(3)},
            lambda *args, **kwargs: ("accepted", None),
            batch_size=4,
        )

        assert (cancelled, cancel_task_run.call_count) == (4, 4)
        assert [call.kwargs for call in list_runs.call_args_list] == [
            {"team_id": 7, "limit": 4},
            {"team_id": 9, "limit": 1},
        ]


@pytest.mark.asyncio
async def test_activity_passes_its_batch_size_and_returns_the_count() -> None:
    environment = ActivityEnvironment()
    # With a heartbeat timeout, the activity sends heartbeats from the thread that runs the sweep.
    environment.info = dataclasses.replace(environment.info, heartbeat_timeout=timedelta(seconds=30))
    heartbeats: list[Any] = []
    environment.on_heartbeat = lambda *details: heartbeats.append(details)

    with patch("products.cloud_agents.backend.temporal.activities.stop_runs_over_quota", return_value=3) as sweep:
        result = await environment.run(stop_cloud_agent_runs_over_quota_activity, StopRunsOverQuotaInputs(batch_size=7))

    assert result == StopRunsOverQuotaResult(cancelled=3)
    sweep.assert_called_once_with(batch_size=7)
    assert heartbeats != []


@pytest_asyncio.fixture(scope="module")
async def workflow_environment() -> AsyncIterator[WorkflowEnvironment]:
    async with await WorkflowEnvironment.start_time_skipping() as environment:
        yield environment


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failures,attempts,succeeds",
    [(0, 1, True), (1, 2, True), (2, 2, False)],
    ids=["first_attempt", "one_retry", "fails_after_its_last_attempt"],
)
async def test_workflow_runs_the_sweep_with_one_retry(
    workflow_environment: WorkflowEnvironment, failures: int, attempts: int, succeeds: bool
) -> None:
    calls: list[StopRunsOverQuotaInputs] = []

    @activity.defn(name="stop_cloud_agent_runs_over_quota_activity")
    async def sweep(inputs: StopRunsOverQuotaInputs) -> StopRunsOverQuotaResult:
        calls.append(inputs)
        if len(calls) <= failures:
            raise RuntimeError("The database is not available.")
        return StopRunsOverQuotaResult(cancelled=5)

    async with Worker(
        workflow_environment.client,
        task_queue=settings.GENERAL_PURPOSE_TASK_QUEUE,
        workflows=[StopCloudAgentRunsOverQuotaWorkflow],
        activities=[sweep],
        workflow_runner=UnsandboxedWorkflowRunner(),
    ):
        execution = workflow_environment.client.execute_workflow(
            WORKFLOW_NAME,
            id=str(uuid.uuid4()),
            task_queue=settings.GENERAL_PURPOSE_TASK_QUEUE,
            execution_timeout=timedelta(minutes=10),
            result_type=StopRunsOverQuotaResult,
        )
        if succeeds:
            assert await execution == StopRunsOverQuotaResult(cancelled=5)
        else:
            with pytest.raises(WorkflowFailureError):
                await execution

    assert calls == [StopRunsOverQuotaInputs(batch_size=sweeps.QUOTA_SWEEP_BATCH_SIZE)] * attempts


@pytest.mark.asyncio
@pytest.mark.parametrize("exists", [False, True], ids=["created", "updated"])
async def test_schedule_runs_every_five_minutes_and_skips_a_run_that_overlaps(exists: bool) -> None:
    schedule_module = "products.cloud_agents.backend.temporal.schedule"
    with (
        patch(f"{schedule_module}.a_schedule_exists", new=AsyncMock(return_value=exists)),
        patch(f"{schedule_module}.a_create_schedule", new=AsyncMock()) as create,
        patch(f"{schedule_module}.a_update_schedule", new=AsyncMock()) as update,
    ):
        await temporal_facade.create_stop_cloud_agent_runs_over_quota_schedule(MagicMock())

    written, unused = (update, create) if exists else (create, update)
    unused.assert_not_called()
    _, schedule_id, schedule = written.call_args.args
    assert schedule_id == SCHEDULE_ID
    assert (schedule.action.workflow, schedule.action.task_queue) == (
        WORKFLOW_NAME,
        settings.GENERAL_PURPOSE_TASK_QUEUE,
    )
    assert [interval.every for interval in schedule.spec.intervals] == [INTERVAL] == [timedelta(minutes=5)]
    assert schedule.policy.overlap == ScheduleOverlapPolicy.SKIP


def test_core_registers_the_workflow_the_activity_and_the_schedule() -> None:
    # Imported here because these modules load every workflow of the repository.
    from posthog.management.commands.start_temporal_worker import ACTIVITIES_DICT, WORKFLOWS_DICT  # noqa: PLC0415
    from posthog.temporal.schedule import schedules  # noqa: PLC0415

    assert StopCloudAgentRunsOverQuotaWorkflow in WORKFLOWS_DICT[settings.GENERAL_PURPOSE_TASK_QUEUE]
    assert stop_cloud_agent_runs_over_quota_activity in ACTIVITIES_DICT[settings.GENERAL_PURPOSE_TASK_QUEUE]
    assert temporal_facade.create_stop_cloud_agent_runs_over_quota_schedule in schedules
