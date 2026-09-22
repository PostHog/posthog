import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from temporalio import activity, workflow
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from products.customer_analytics.backend.facade.temporal_contracts import (
    DispatchAccountPropertySyncInput,
    FinalizeAccountPropertySyncRunsInput,
    StageAccountPropertySyncInput,
)
from products.customer_analytics.backend.temporal.account_property_sync import (
    AccountPropertySyncInput,
    StageWarehouseAccountPropertiesWorkflow,
    SyncWarehouseAccountPropertiesWorkflow,
    dispatch_warehouse_account_property_sync_activity,
    finalize_warehouse_account_property_runs_activity,
    stage_warehouse_account_property_files_activity,
    start_warehouse_account_property_runs_activity,
    sync_warehouse_account_properties_activity,
)

pytestmark = pytest.mark.asyncio


def _staging_input() -> StageAccountPropertySyncInput:
    return StageAccountPropertySyncInput(
        team_id=7,
        saved_query_id="019f0000-0000-7000-8000-000000000001",
        job_id="job-1",
        table_uri="s3://data-warehouse/dlt/table",
        delta_version=5,
    )


@asynccontextmanager
async def _no_heartbeat() -> AsyncIterator[None]:
    yield


async def test_staging_activity_reads_the_committed_delta_version() -> None:
    sink = MagicMock()
    sink.stage_delta_snapshot = AsyncMock(return_value=True)

    with (
        patch(
            "products.customer_analytics.backend.temporal.account_property_sync.AccountPropertyRowSink",
            return_value=sink,
        ),
        patch(
            "products.customer_analytics.backend.temporal.account_property_sync.Heartbeater",
            return_value=_no_heartbeat(),
        ),
        patch("products.customer_analytics.backend.temporal.account_property_sync.activity.info") as activity_info,
        patch(
            "products.customer_analytics.backend.temporal.account_property_sync.update_account_property_sync_runs_phase"
        ),
    ):
        activity_info.return_value.attempt = 1
        activity_info.return_value.workflow_id = "stage-workflow-job-1"
        staged = await stage_warehouse_account_property_files_activity(_staging_input())

    assert staged is True
    sink.stage_delta_snapshot.assert_awaited_once_with("s3://data-warehouse/dlt/table", 5)


async def test_staging_workflow_opens_history_before_staging_and_dispatches_after_success() -> None:
    execute_activity = AsyncMock(side_effect=[None, True, None])

    with (
        patch.object(workflow, "execute_activity", new=execute_activity),
        patch.object(workflow, "patched", return_value=True),
    ):
        await StageWarehouseAccountPropertiesWorkflow().run(_staging_input())

    assert [call.args[0] for call in execute_activity.await_args_list] == [
        start_warehouse_account_property_runs_activity,
        stage_warehouse_account_property_files_activity,
        dispatch_warehouse_account_property_sync_activity,
    ]


async def test_staging_workflow_preserves_the_pre_history_command_sequence() -> None:
    execute_activity = AsyncMock(side_effect=[True, None])

    with (
        patch.object(workflow, "execute_activity", new=execute_activity),
        patch.object(workflow, "patched", return_value=False),
    ):
        await StageWarehouseAccountPropertiesWorkflow().run(_staging_input())

    assert [call.args[0] for call in execute_activity.await_args_list] == [
        stage_warehouse_account_property_files_activity,
        dispatch_warehouse_account_property_sync_activity,
    ]


async def test_staging_workflow_finishes_empty_history_when_no_sources_remain() -> None:
    execute_activity = AsyncMock(side_effect=[None, False, None])

    with (
        patch.object(workflow, "execute_activity", new=execute_activity),
        patch.object(workflow, "patched", return_value=True),
    ):
        await StageWarehouseAccountPropertiesWorkflow().run(_staging_input())

    assert execute_activity.await_args_list[-1].args[0] == finalize_warehouse_account_property_runs_activity
    finalization = execute_activity.await_args_list[-1].args[1]
    assert isinstance(finalization, FinalizeAccountPropertySyncRunsInput)
    assert (finalization.status, finalization.phase, finalization.error) == ("completed", "completed", None)


@pytest.mark.parametrize(
    "activity_results,failed_phase",
    [
        ([None, RuntimeError("staging failed"), None], "staging"),
        ([None, True, RuntimeError("dispatch failed"), None], "dispatching"),
    ],
)
async def test_staging_workflow_finishes_failed_history(activity_results: list[object], failed_phase: str) -> None:
    execute_activity = AsyncMock(side_effect=activity_results)

    with (
        pytest.raises(RuntimeError),
        patch.object(workflow, "execute_activity", new=execute_activity),
        patch.object(workflow, "patched", return_value=True),
    ):
        await StageWarehouseAccountPropertiesWorkflow().run(_staging_input())

    finalization = execute_activity.await_args_list[-1].args[1]
    assert isinstance(finalization, FinalizeAccountPropertySyncRunsInput)
    assert (finalization.status, finalization.phase) == ("failed", failed_phase)
    assert finalization.error is not None


async def test_staging_and_dispatch_recover_from_transient_activity_failures() -> None:
    attempts: list[tuple[str, int]] = []

    @activity.defn(name="start-warehouse-account-property-runs")
    async def start_runs(_input: DispatchAccountPropertySyncInput) -> None:
        return None

    @activity.defn(name="stage-warehouse-account-property-files")
    async def stage_files(_input: StageAccountPropertySyncInput) -> bool:
        attempt = activity.info().attempt
        attempts.append(("stage", attempt))
        if attempt == 1:
            raise RuntimeError("staging temporarily unavailable")
        return True

    @activity.defn(name="dispatch-warehouse-account-property-sync")
    async def dispatch(_input: DispatchAccountPropertySyncInput) -> None:
        attempt = activity.info().attempt
        attempts.append(("dispatch", attempt))
        if attempt == 1:
            raise RuntimeError("Temporal temporarily unavailable")

    task_queue = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as environment:
        async with Worker(
            environment.client,
            task_queue=task_queue,
            workflows=[StageWarehouseAccountPropertiesWorkflow],
            activities=[start_runs, stage_files, dispatch],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            await environment.client.execute_workflow(
                StageWarehouseAccountPropertiesWorkflow.run,
                _staging_input(),
                id=str(uuid.uuid4()),
                task_queue=task_queue,
            )

    assert attempts == [("stage", 1), ("stage", 2), ("dispatch", 1), ("dispatch", 2)]


async def test_dispatch_starts_missing_segment_when_its_sibling_already_runs() -> None:
    client = AsyncMock()
    client.start_workflow.side_effect = [WorkflowAlreadyStartedError("tracked", "workflow"), None]
    input = DispatchAccountPropertySyncInput(
        team_id=7,
        saved_query_id="019f0000-0000-7000-8000-000000000001",
        job_id="job-1",
    )

    with (
        patch("products.customer_analytics.backend.temporal.account_property_sync.async_connect", return_value=client),
        patch("products.customer_analytics.backend.temporal.account_property_sync.activity.info") as activity_info,
        patch(
            "products.customer_analytics.backend.temporal.account_property_sync.update_account_property_sync_runs_phase"
        ),
    ):
        activity_info.return_value.attempt = 1
        activity_info.return_value.workflow_id = "stage-workflow-job-1"
        await dispatch_warehouse_account_property_sync_activity(input)

    assert client.start_workflow.await_count == 2
    assert [call.args[1].segment for call in client.start_workflow.await_args_list] == ["tracked", "ignored"]


async def test_workflow_executes_one_retryable_segment_activity() -> None:
    execute_activity = AsyncMock()
    input = AccountPropertySyncInput(
        team_id=7,
        saved_query_id="019f0000-0000-7000-8000-000000000001",
        job_id="job-1",
        segment="tracked",
    )

    with patch.object(workflow, "execute_activity", new=execute_activity):
        await SyncWarehouseAccountPropertiesWorkflow().run(input)

    execute_activity.assert_awaited_once()
    assert execute_activity.await_args is not None
    assert execute_activity.await_args.args == (sync_warehouse_account_properties_activity, input)
    assert execute_activity.await_args.kwargs["retry_policy"].maximum_attempts == 5
