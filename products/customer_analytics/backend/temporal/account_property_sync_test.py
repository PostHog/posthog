import uuid
import asyncio
from collections import deque
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, nullcontext
from dataclasses import replace
from types import SimpleNamespace

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from django.test import override_settings

from temporalio import activity, workflow
from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import ApplicationError, WorkflowAlreadyStartedError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Replayer, UnsandboxedWorkflowRunner, Worker

from products.customer_analytics.backend.facade.temporal_contracts import (
    AccountPropertySyncCoordinatorInput,
    AccountPropertySyncWork,
    DispatchAccountPropertySyncInput,
    FinalizeAccountPropertySyncRunsInput,
    StageAccountPropertySyncInput,
)
from products.customer_analytics.backend.temporal.account_property_sync import (
    AccountPropertySyncCoordinatorWorkflow,
    AccountPropertySyncInput,
    StageWarehouseAccountPropertiesWorkflow,
    SyncWarehouseAccountPropertiesWorkflow,
    dispatch_warehouse_account_property_sync_activity,
    finalize_warehouse_account_property_runs_activity,
    stage_warehouse_account_property_files_activity,
    start_warehouse_account_property_runs_activity,
    sync_warehouse_account_properties_activity,
    wake_account_property_sync_coordinator,
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
            workflow_id = str(uuid.uuid4())
            await environment.client.execute_workflow(
                StageWarehouseAccountPropertiesWorkflow.run,
                _staging_input(),
                id=workflow_id,
                task_queue=task_queue,
            )
            history = await environment.client.get_workflow_handle(workflow_id).fetch_history()
            await Replayer(
                workflows=[StageWarehouseAccountPropertiesWorkflow],
                workflow_runner=UnsandboxedWorkflowRunner(),
            ).replay_workflow(history)

    assert attempts == [("stage", 1), ("stage", 2), ("dispatch", 1), ("dispatch", 2)]


@pytest.mark.parametrize("coordinated", [False, True])
async def test_dispatch_starts_missing_segment_or_delegates_to_coordinator(coordinated: bool) -> None:
    client = AsyncMock()
    if not coordinated:
        client.start_workflow.side_effect = [WorkflowAlreadyStartedError("tracked", "workflow"), None]
    input = DispatchAccountPropertySyncInput(
        team_id=7,
        saved_query_id="019f0000-0000-7000-8000-000000000001",
        job_id="job-1",
    )

    with (
        override_settings(ACCOUNT_PROPERTY_SYNC_COORDINATION_ENABLED=coordinated),
        patch("products.customer_analytics.backend.temporal.account_property_sync.async_connect", return_value=client),
        patch(
            "products.customer_analytics.backend.temporal.account_property_sync.resolve_effective_team_id",
            side_effect=lambda team_id: team_id,
        ),
        patch("products.customer_analytics.backend.temporal.account_property_sync.activity.info") as activity_info,
        patch(
            "products.customer_analytics.backend.temporal.account_property_sync.request_account_property_sync"
        ) as request,
        patch(
            "products.customer_analytics.backend.temporal.account_property_sync.update_account_property_sync_runs_phase"
        ),
    ):
        activity_info.return_value.attempt = 1
        activity_info.return_value.workflow_id = "stage-workflow-job-1"
        await dispatch_warehouse_account_property_sync_activity(input)

    if coordinated:
        request.assert_called_once_with(team_id=input.team_id, saved_query_id=input.saved_query_id, job_id=input.job_id)
        client.start_workflow.assert_awaited_once()
        assert client.start_workflow.await_args.kwargs["start_signal"] == "wake"
    else:
        request.assert_not_called()
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


def _coordinator_work() -> AccountPropertySyncWork:
    return AccountPropertySyncWork(
        team_id=7,
        saved_query_id=_staging_input().saved_query_id,
        request_id="request-1",
        job_id="job-1",
        kind="staged",
        generation=1,
        started_at="2026-01-01T00:00:00+00:00",
    )


@pytest.mark.parametrize("tracked_outcome", ["failed", "retry-exhausted", "deferred", "completed"])
async def test_coordinator_settles_siblings_preserves_followup_and_recovers(tracked_outcome: str) -> None:
    first = _coordinator_work()
    followup = replace(first, request_id="request-2", job_id="job-2", kind="live", generation=2)
    pending = deque([first, followup])
    claimed: list[str] = []
    finished: list[tuple[str, str | None]] = []
    attempts: dict[str, int] = {}
    tracked_settled = asyncio.Event()
    ignored_started = asyncio.Event()
    release_ignored = asyncio.Event()

    @activity.defn(name="get-next-account-property-sync")
    async def get_next(_input: AccountPropertySyncCoordinatorInput) -> AccountPropertySyncWork | None:
        if not pending:
            return None
        work = pending.popleft()
        claimed.append(work.request_id)
        return work

    @activity.defn(name="sync_warehouse_account_properties_activity")
    async def sync_segment(input: AccountPropertySyncInput) -> dict[str, int]:
        assert input.request_id == first.request_id
        attempts[input.segment] = attempts.get(input.segment, 0) + 1
        if input.segment == "ignored":
            ignored_started.set()
            await release_ignored.wait()
            return {"written": 1, "deferred": int(attempts[input.segment] == 1)}
        await ignored_started.wait()
        tracked_settled.set()
        if tracked_outcome == "failed":
            raise ApplicationError("invalid source", non_retryable=True)
        if tracked_outcome == "retry-exhausted":
            raise RuntimeError("source unavailable")
        if tracked_outcome == "deferred" and attempts[input.segment] == 1:
            return {"deferred": 1}
        return {"written": 1}

    @activity.defn(name="sync-live-account-properties")
    async def sync_live(input: AccountPropertySyncWork) -> dict[str, int]:
        assert finished[0][0] == first.request_id
        attempts[input.request_id] = attempts.get(input.request_id, 0) + 1
        return {"deferred": int(attempts[input.request_id] == 1)}

    @activity.defn(name="finish-account-property-sync")
    async def finish(input: AccountPropertySyncWork, error: str | None) -> None:
        finished.append((input.request_id, error))

    input = AccountPropertySyncCoordinatorInput(team_id=first.team_id, saved_query_id=first.saved_query_id)
    workflow_id = f"coordinate-account-properties-{input.team_id}-{input.saved_query_id}"
    task_queue = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as environment:
        with (
            override_settings(DATA_WAREHOUSE_METADATA_TASK_QUEUE=task_queue),
            patch(
                "products.customer_analytics.backend.temporal.account_property_sync.async_connect",
                return_value=environment.client,
            ),
            patch(
                "products.customer_analytics.backend.temporal.account_property_sync.resolve_effective_team_id",
                side_effect=lambda team_id: team_id,
            ),
        ):
            async with Worker(
                environment.client,
                task_queue=task_queue,
                workflows=[AccountPropertySyncCoordinatorWorkflow],
                activities=[get_next, sync_segment, sync_live, finish],
                workflow_runner=UnsandboxedWorkflowRunner(),
            ):
                await wake_account_property_sync_coordinator(input)
                handle = environment.client.get_workflow_handle(workflow_id)
                await asyncio.wait_for(tracked_settled.wait(), timeout=30)
                for _ in range(3):
                    await wake_account_property_sync_coordinator(input)
                assert claimed == [first.request_id]
                assert finished == []
                release_ignored.set()
                await handle.result()
                history = await handle.fetch_history()
                await Replayer(
                    workflows=[AccountPropertySyncCoordinatorWorkflow],
                    workflow_runner=UnsandboxedWorkflowRunner(),
                ).replay_workflow(history)

                assert claimed == [first.request_id, followup.request_id]
                assert finished[0][0] == first.request_id
                assert bool(finished[0][1]) == (tracked_outcome in ("failed", "retry-exhausted"))
                if tracked_outcome == "failed":
                    assert "invalid source" in (finished[0][1] or "")
                assert finished[1] == (followup.request_id, None)
                assert attempts == {
                    "tracked": 5 if tracked_outcome == "retry-exhausted" else 2 if tracked_outcome == "deferred" else 1,
                    "ignored": 2,
                    followup.request_id: 2,
                }

                recovered = replace(followup, request_id="request-3", job_id="job-3", generation=3)
                pending.append(recovered)
                await wake_account_property_sync_coordinator(input)
                await environment.client.get_workflow_handle(workflow_id).result()
                assert claimed == [first.request_id, followup.request_id, recovered.request_id]
                assert finished[-1] == (recovered.request_id, None)


@pytest.mark.parametrize("input_team_id", [7, 8])
async def test_wake_uses_atomic_signal_with_start_on_the_canonical_project(input_team_id: int) -> None:
    client = AsyncMock()
    input = AccountPropertySyncCoordinatorInput(team_id=input_team_id, saved_query_id=_staging_input().saved_query_id)
    with (
        patch("products.customer_analytics.backend.temporal.account_property_sync.async_connect", return_value=client),
        patch(
            "products.customer_analytics.backend.temporal.account_property_sync.resolve_effective_team_id",
            return_value=7,
        ),
    ):
        await wake_account_property_sync_coordinator(input)
    kwargs = client.start_workflow.await_args.kwargs
    assert kwargs["id"] == f"coordinate-account-properties-7-{input.saved_query_id}"
    assert kwargs["id_conflict_policy"] == WorkflowIDConflictPolicy.USE_EXISTING
    assert kwargs["id_reuse_policy"] == WorkflowIDReusePolicy.ALLOW_DUPLICATE
    assert kwargs["start_signal"] == "wake"


@pytest.mark.parametrize("coordinated,request_id", [(False, None), (True, None), (True, "existing-request")])
async def test_celery_sync_routes_bulk_by_coordination_setting(coordinated: bool, request_id: str | None) -> None:
    from products.customer_analytics.backend.tasks.tasks import process_custom_property_sync

    wake = AsyncMock()
    with (
        override_settings(ACCOUNT_PROPERTY_SYNC_COORDINATION_ENABLED=coordinated),
        patch(
            "products.customer_analytics.backend.logic.account_property_coordination.request_account_property_sync"
        ) as request,
        patch(
            "products.customer_analytics.backend.temporal.account_property_sync.wake_account_property_sync_coordinator",
            wake,
        ),
        patch("products.customer_analytics.backend.tasks.tasks.sync_custom_property_values") as bulk,
    ):
        await asyncio.to_thread(process_custom_property_sync, 7, _staging_input().saved_query_id, request_id)
    if coordinated:
        bulk.assert_not_called()
        assert request.call_count == int(request_id is None)
        wake.assert_awaited_once_with(
            AccountPropertySyncCoordinatorInput(team_id=7, saved_query_id=_staging_input().saved_query_id)
        )
    else:
        request.assert_not_called()
        wake.assert_not_awaited()
        bulk.assert_called_once_with(team_id=7, saved_query_id=_staging_input().saved_query_id)


async def test_recovery_keeps_waking_after_an_individual_failure() -> None:
    from products.customer_analytics.backend.tasks.tasks import recover_pending_account_property_syncs

    wake = AsyncMock(side_effect=[RuntimeError("Temporal unavailable"), None])
    with (
        override_settings(ACCOUNT_PROPERTY_SYNC_COORDINATION_ENABLED=True),
        patch(
            "products.customer_analytics.backend.logic.account_property_coordination.list_pending_account_property_syncs",
            return_value=[(7, "view-1"), (8, "view-2")],
        ),
        patch(
            "products.customer_analytics.backend.temporal.account_property_sync.wake_account_property_sync_coordinator",
            wake,
        ),
        patch("products.customer_analytics.backend.tasks.tasks.capture_exception") as capture,
    ):
        await asyncio.to_thread(recover_pending_account_property_syncs)
    assert [call.args[0].saved_query_id for call in wake.await_args_list] == ["view-1", "view-2"]
    capture.assert_called_once()


async def test_coordinator_resumes_inflight_work_after_worker_restart() -> None:
    work = replace(_coordinator_work(), kind="live")
    input = AccountPropertySyncCoordinatorInput(team_id=work.team_id, saved_query_id=work.saved_query_id)
    activity_started = asyncio.Event()
    resumed = False
    completed = False
    calls = 0

    @activity.defn(name="get-next-account-property-sync")
    async def get_next(_input: AccountPropertySyncCoordinatorInput) -> AccountPropertySyncWork | None:
        return None if completed else work

    @activity.defn(name="sync-live-account-properties")
    async def sync_live(input: AccountPropertySyncWork) -> dict[str, int]:
        nonlocal calls
        assert input.request_id == work.request_id
        calls += 1
        if not resumed:
            activity_started.set()
            await activity.wait_for_worker_shutdown()
            raise RuntimeError("Worker stopped before the activity completed")
        return {"written": 1}

    @activity.defn(name="finish-account-property-sync")
    async def finish(input: AccountPropertySyncWork, error: str | None) -> None:
        nonlocal completed
        assert input.request_id == work.request_id
        assert error is None
        completed = True

    task_queue = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as environment:
        async with Worker(
            environment.client,
            task_queue=task_queue,
            workflows=[AccountPropertySyncCoordinatorWorkflow],
            activities=[get_next, sync_live, finish],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            handle = await environment.client.start_workflow(
                AccountPropertySyncCoordinatorWorkflow.run,
                input,
                id=str(uuid.uuid4()),
                task_queue=task_queue,
            )
            await asyncio.wait_for(activity_started.wait(), timeout=30)
        resumed = True
        async with Worker(
            environment.client,
            task_queue=task_queue,
            workflows=[AccountPropertySyncCoordinatorWorkflow],
            activities=[get_next, sync_live, finish],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            await handle.result()
    assert completed
    assert calls == 2


async def test_legacy_segment_on_enabled_worker_registers_instead_of_writing() -> None:
    input = AccountPropertySyncInput(
        team_id=7, saved_query_id=_staging_input().saved_query_id, job_id="job-1", segment="tracked"
    )
    with (
        override_settings(ACCOUNT_PROPERTY_SYNC_COORDINATION_ENABLED=True),
        patch(
            "products.customer_analytics.backend.temporal.account_property_sync.request_account_property_sync"
        ) as request,
        patch(
            "products.customer_analytics.backend.temporal.account_property_sync.wake_account_property_sync_coordinator",
            new_callable=AsyncMock,
        ) as wake,
        patch(
            "products.customer_analytics.backend.temporal.account_property_sync.run_account_property_segment_sync",
            new_callable=AsyncMock,
        ) as bulk,
    ):
        result = await sync_warehouse_account_properties_activity(input)
    assert result == {"delegated": 1}
    request.assert_called_once_with(team_id=input.team_id, saved_query_id=input.saved_query_id, job_id=input.job_id)
    wake.assert_awaited_once()
    bulk.assert_not_awaited()


@pytest.mark.parametrize("outcome", ["completed", "deferred", "invalid", "superseded", "superseded-after-read"])
async def test_live_activity_defers_health_and_treats_supersession_as_benign(outcome: str) -> None:
    from products.customer_analytics.backend.logic.account_property_coordination import AccountPropertySyncSuperseded
    from products.customer_analytics.backend.temporal.account_property_sync import sync_live_account_properties_activity

    work = replace(_coordinator_work(), kind="live")
    source_id = str(uuid.uuid4())
    result = SimpleNamespace(
        view_found=True,
        written=3,
        unmatched_keys=1,
        accounts_total=4,
        rows_fetched=5,
        source_errors={source_id: "invalid value"} if outcome == "invalid" else {},
        deferred=int(outcome == "deferred"),
    )
    with (
        patch("products.customer_analytics.backend.temporal.account_property_sync.activity.info") as info,
        patch(
            "products.customer_analytics.backend.temporal.account_property_sync.Heartbeater",
            return_value=_no_heartbeat(),
        ),
        patch(
            "products.customer_analytics.backend.temporal.account_property_sync.begin_account_property_sync_attempt"
        ) as begin,
        patch(
            "products.customer_analytics.backend.temporal.account_property_sync.guard_account_property_sync_attempt",
            return_value=nullcontext(),
        ) as guard,
        patch(
            "products.customer_analytics.backend.temporal.account_property_sync.sync_custom_property_values",
            return_value=result,
        ) as read,
        patch(
            "products.customer_analytics.backend.temporal.account_property_sync.start_account_property_sync_runs"
        ) as start,
        patch(
            "products.customer_analytics.backend.temporal.account_property_sync.update_account_property_sync_runs_phase"
        ),
        patch(
            "products.customer_analytics.backend.temporal.account_property_sync.finish_account_property_sync_runs"
        ) as finish,
        patch(
            "products.customer_analytics.backend.temporal.account_property_sync.finalize_account_property_sync_runs"
        ) as finalize,
        patch("products.customer_analytics.backend.temporal.account_property_sync.capture_exception"),
    ):
        info.return_value.attempt = 1
        if outcome == "superseded":
            begin.side_effect = AccountPropertySyncSuperseded()
        if outcome == "superseded-after-read":
            guard.side_effect = [nullcontext(), AccountPropertySyncSuperseded()]
        if outcome == "invalid":
            with pytest.raises(ApplicationError) as error:
                await sync_live_account_properties_activity(work)
            assert error.value.non_retryable
            assert finish.call_args_list[0].args[2][0].error == "invalid value"
        else:
            counts = await sync_live_account_properties_activity(work)
            if outcome in ("superseded", "superseded-after-read"):
                assert counts == {"superseded": 1}
                if outcome == "superseded":
                    start.assert_not_called()
                    read.assert_not_called()
                else:
                    read.assert_called_once()
            else:
                assert counts == {
                    "written": 3,
                    "unmatched_keys": 1,
                    "accounts_total": 4,
                    "rows_fetched": 5,
                    "source_errors": 0,
                    "deferred": int(outcome == "deferred"),
                }
                assert read.call_args.kwargs["sync_read"] is begin.return_value
        if outcome in ("deferred", "superseded", "superseded-after-read"):
            finish.assert_not_called()
            finalize.assert_not_called()
