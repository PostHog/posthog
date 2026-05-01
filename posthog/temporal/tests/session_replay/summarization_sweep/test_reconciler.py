import uuid
from typing import Any

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import temporalio.worker
from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from posthog.models.team import Team
from posthog.temporal.session_replay.summarization_sweep.activities import (
    list_enabled_teams_activity,
    list_summarization_schedule_team_ids_activity,
    upsert_team_schedule_activity,
)
from posthog.temporal.session_replay.summarization_sweep.constants import (
    RECONCILER_WORKFLOW_NAME,
    SCHEDULE_ID_PREFIX,
    SCHEDULE_TYPE,
    WORKFLOW_NAME,
)
from posthog.temporal.session_replay.summarization_sweep.models import (
    DeleteTeamScheduleInput,
    ReconcileSchedulesInputs,
    UpsertTeamScheduleInput,
)
from posthog.temporal.session_replay.summarization_sweep.reconciler import ReconcileSummarizationSchedulesWorkflow

from products.signals.backend.models import SignalSourceConfig

from .conftest import enable_signal_source


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_list_enabled_teams_empty(activity_environment):
    result = await activity_environment.run(list_enabled_teams_activity)
    assert result == []


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_list_enabled_teams_returns_enabled_only(activity_environment, organization):
    from asgiref.sync import sync_to_async

    t_enabled = await sync_to_async(Team.objects.create)(organization=organization, name="enabled")
    t_disabled = await sync_to_async(Team.objects.create)(organization=organization, name="disabled")
    t_none = await sync_to_async(Team.objects.create)(organization=organization, name="none")
    await sync_to_async(enable_signal_source)(t_enabled, enabled=True)
    await sync_to_async(enable_signal_source)(t_disabled, enabled=False)

    result = await activity_environment.run(list_enabled_teams_activity)
    assert t_enabled.id in result
    assert t_disabled.id not in result
    assert t_none.id not in result


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_list_enabled_teams_ignores_other_source_types(activity_environment, team):
    from asgiref.sync import sync_to_async

    def _create_other() -> None:
        SignalSourceConfig.objects.create(
            team=team,
            source_product=SignalSourceConfig.SourceProduct.ERROR_TRACKING,
            source_type=SignalSourceConfig.SourceType.ISSUE_CREATED,
            enabled=True,
        )

    await sync_to_async(_create_other)()
    result = await activity_environment.run(list_enabled_teams_activity)
    assert team.id not in result


def _make_listing(schedule_id: str, workflow_type: str = WORKFLOW_NAME) -> Any:
    action = MagicMock()
    action.workflow = workflow_type
    schedule = MagicMock()
    schedule.action = action
    listing = MagicMock()
    listing.id = schedule_id
    listing.schedule = schedule
    return listing


class _AsyncIter:
    def __init__(self, items: list[Any]) -> None:
        self._items = items

    def __aiter__(self):
        self._iter = iter(self._items)
        return self

    async def __anext__(self):
        try:
            return next(self._iter)
        except StopIteration:
            raise StopAsyncIteration


@pytest.mark.asyncio
async def test_list_summarization_schedule_team_ids_queries_by_schedule_type(activity_environment):
    listings = [
        _make_listing(f"{SCHEDULE_ID_PREFIX}-101"),
        _make_listing(f"{SCHEDULE_ID_PREFIX}-202"),
        # Belt-and-suspenders: guard trips if someone sets the attribute with the wrong workflow type.
        _make_listing(f"{SCHEDULE_ID_PREFIX}-303", workflow_type="some-other-workflow"),
        _make_listing("some-other-schedule-id"),
        _make_listing(f"{SCHEDULE_ID_PREFIX}-notanint"),
    ]
    client = MagicMock()
    client.list_schedules = AsyncMock(return_value=_AsyncIter(listings))
    with patch(
        "posthog.temporal.common.client.async_connect",
        AsyncMock(return_value=client),
    ):
        result = await activity_environment.run(list_summarization_schedule_team_ids_activity)
    assert sorted(result) == [101, 202]
    call_kwargs = client.list_schedules.call_args.kwargs
    assert call_kwargs["query"] == f'PostHogScheduleType = "{SCHEDULE_TYPE}"'


@pytest.mark.asyncio
async def test_upsert_team_schedule_activity_delegates(activity_environment):
    with patch(
        "posthog.temporal.session_replay.summarization_sweep.schedule.a_upsert_team_schedule",
        AsyncMock(),
    ) as mock_upsert:
        await activity_environment.run(upsert_team_schedule_activity, UpsertTeamScheduleInput(team_id=42))
    mock_upsert.assert_awaited_once_with(42)


@pytest.mark.asyncio
async def test_reconcile_workflow_upserts_new_and_deletes_stale():
    upserted_ids: list[int] = []
    deleted_ids: list[int] = []

    @activity.defn(name="list_enabled_teams_activity")
    async def list_enabled_mocked() -> list[int]:
        return [1, 2, 3]

    @activity.defn(name="list_summarization_schedule_team_ids_activity")
    async def list_schedules_mocked() -> list[int]:
        return [2, 3, 4]

    @activity.defn(name="upsert_team_schedule_activity")
    async def upsert_mocked(inputs: UpsertTeamScheduleInput) -> None:
        upserted_ids.append(inputs.team_id)

    @activity.defn(name="delete_team_schedule_activity")
    async def delete_mocked(inputs: DeleteTeamScheduleInput) -> None:
        deleted_ids.append(inputs.team_id)

    task_queue = str(uuid.uuid4())
    workflow_id = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[ReconcileSummarizationSchedulesWorkflow],
            activities=[list_enabled_mocked, list_schedules_mocked, upsert_mocked, delete_mocked],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            result = await env.client.execute_workflow(
                RECONCILER_WORKFLOW_NAME,
                ReconcileSchedulesInputs(),
                id=workflow_id,
                task_queue=task_queue,
            )

    assert sorted(upserted_ids) == [1]
    assert sorted(deleted_ids) == [4]
    assert result["upserted"] == 1
    assert result["deleted"] == 1
    assert result["failed_upsert"] == 0
    assert result["failed_delete"] == 0


@pytest.mark.asyncio
async def test_reconcile_workflow_noop_when_in_sync():
    @activity.defn(name="list_enabled_teams_activity")
    async def list_enabled_mocked() -> list[int]:
        return [1, 2]

    @activity.defn(name="list_summarization_schedule_team_ids_activity")
    async def list_schedules_mocked() -> list[int]:
        return [1, 2]

    upsert_mock = AsyncMock()
    delete_mock = AsyncMock()

    @activity.defn(name="upsert_team_schedule_activity")
    async def upsert_mocked(inputs: UpsertTeamScheduleInput) -> None:
        await upsert_mock(inputs)

    @activity.defn(name="delete_team_schedule_activity")
    async def delete_mocked(inputs: DeleteTeamScheduleInput) -> None:
        await delete_mock(inputs)

    task_queue = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[ReconcileSummarizationSchedulesWorkflow],
            activities=[list_enabled_mocked, list_schedules_mocked, upsert_mocked, delete_mocked],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            result = await env.client.execute_workflow(
                RECONCILER_WORKFLOW_NAME,
                ReconcileSchedulesInputs(),
                id=str(uuid.uuid4()),
                task_queue=task_queue,
            )

    upsert_mock.assert_not_awaited()
    delete_mock.assert_not_awaited()
    assert result == {"upserted": 0, "deleted": 0, "failed_upsert": 0, "failed_delete": 0, "dry_run": False}


@pytest.mark.asyncio
async def test_reconcile_workflow_isolates_per_team_failures():
    @activity.defn(name="list_enabled_teams_activity")
    async def list_enabled_mocked() -> list[int]:
        return [1, 2, 3]

    @activity.defn(name="list_summarization_schedule_team_ids_activity")
    async def list_schedules_mocked() -> list[int]:
        return []

    seen: list[int] = []

    @activity.defn(name="upsert_team_schedule_activity")
    async def upsert_mocked(inputs: UpsertTeamScheduleInput) -> None:
        seen.append(inputs.team_id)
        if inputs.team_id == 2:
            raise RuntimeError("boom")

    @activity.defn(name="delete_team_schedule_activity")
    async def delete_mocked(inputs: DeleteTeamScheduleInput) -> None:
        pass

    task_queue = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[ReconcileSummarizationSchedulesWorkflow],
            activities=[list_enabled_mocked, list_schedules_mocked, upsert_mocked, delete_mocked],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            result = await env.client.execute_workflow(
                RECONCILER_WORKFLOW_NAME,
                ReconcileSchedulesInputs(),
                id=str(uuid.uuid4()),
                task_queue=task_queue,
            )

    assert sorted(set(seen)) == [1, 2, 3]
    assert result["upserted"] == 2
    assert result["failed_upsert"] == 1
    assert result["deleted"] == 0
    assert result["failed_delete"] == 0


@pytest.mark.asyncio
async def test_reconcile_workflow_dry_run_does_not_mutate():
    upsert_inputs: list[UpsertTeamScheduleInput] = []
    delete_inputs: list[DeleteTeamScheduleInput] = []

    @activity.defn(name="list_enabled_teams_activity")
    async def list_enabled_mocked() -> list[int]:
        return [1, 2]

    @activity.defn(name="list_summarization_schedule_team_ids_activity")
    async def list_schedules_mocked() -> list[int]:
        return [2, 3]

    @activity.defn(name="upsert_team_schedule_activity")
    async def upsert_mocked(inputs: UpsertTeamScheduleInput) -> None:
        upsert_inputs.append(inputs)

    @activity.defn(name="delete_team_schedule_activity")
    async def delete_mocked(inputs: DeleteTeamScheduleInput) -> None:
        delete_inputs.append(inputs)

    task_queue = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[ReconcileSummarizationSchedulesWorkflow],
            activities=[list_enabled_mocked, list_schedules_mocked, upsert_mocked, delete_mocked],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            result = await env.client.execute_workflow(
                RECONCILER_WORKFLOW_NAME,
                ReconcileSchedulesInputs(dry_run=True),
                id=str(uuid.uuid4()),
                task_queue=task_queue,
            )

    assert upsert_inputs == [UpsertTeamScheduleInput(team_id=1, dry_run=True)]
    assert delete_inputs == [DeleteTeamScheduleInput(team_id=3, dry_run=True)]
    assert result == {"upserted": 1, "deleted": 1, "failed_upsert": 0, "failed_delete": 0, "dry_run": True}


def test_reconcile_workflow_parse_inputs_dry_run():
    import json

    assert ReconcileSummarizationSchedulesWorkflow.parse_inputs([]) == ReconcileSchedulesInputs()
    assert ReconcileSummarizationSchedulesWorkflow.parse_inputs(
        [json.dumps({"dry_run": True})]
    ) == ReconcileSchedulesInputs(dry_run=True)


def test_summarize_team_workflow_parse_inputs_dry_run():
    import json

    from posthog.temporal.session_replay.summarization_sweep.models import SummarizeTeamSessionsInputs
    from posthog.temporal.session_replay.summarization_sweep.workflow import SummarizeTeamSessionsWorkflow

    assert SummarizeTeamSessionsWorkflow.parse_inputs([json.dumps({"team_id": 42})]) == SummarizeTeamSessionsInputs(
        team_id=42
    )
    assert SummarizeTeamSessionsWorkflow.parse_inputs(
        [json.dumps({"team_id": 42, "dry_run": True})]
    ) == SummarizeTeamSessionsInputs(team_id=42, dry_run=True)
