import uuid
import asyncio
import dataclasses
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Any

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from temporalio import activity, workflow
from temporalio.client import WorkflowFailureError
from temporalio.common import RetryPolicy
from temporalio.exceptions import (
    ActivityError,
    ApplicationError,
    TimeoutError,
    TimeoutType,
    WorkflowAlreadyStartedError,
)
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Replayer, UnsandboxedWorkflowRunner, Worker

from products.customer_analytics.backend.facade.temporal_contracts import (
    AccountPropertySegmentTelemetryInput,
    AccountPropertySourceSyncInput,
    DispatchAccountPropertySyncInput,
    FinalizeAccountPropertySyncRunsInput,
    StageAccountPropertySyncInput,
)
from products.customer_analytics.backend.logic.account_property_sync import AccountPropertySourceValueError
from products.customer_analytics.backend.temporal.account_property_sync import (
    ACCOUNT_PROPERTY_SYNC_ACTIVITIES,
    ACCOUNT_PROPERTY_SYNC_WORKFLOW_NAME,
    ACCOUNT_PROPERTY_SYNC_WORKFLOWS,
    AccountPropertySyncInput,
    StageWarehouseAccountPropertiesWorkflow,
    SyncWarehouseAccountPropertiesFanoutWorkflow,
    SyncWarehouseAccountPropertiesWorkflow,
    complete_warehouse_account_property_segment_activity,
    dispatch_warehouse_account_property_sync_activity,
    emit_warehouse_account_property_segment_telemetry_activity,
    finalize_warehouse_account_property_runs_activity,
    list_warehouse_account_property_sources_activity,
    stage_warehouse_account_property_files_activity,
    start_warehouse_account_property_runs_activity,
    sync_warehouse_account_properties_activity,
    sync_warehouse_account_property_source_activity,
)

pytestmark = pytest.mark.asyncio

_MODULE = "products.customer_analytics.backend.temporal.account_property_sync"
_SOURCE_COUNTS = {"rows_read": 10, "changed": 4, "matched": 3, "written": 2, "source_errors": 0, "source_count": 2}
_FAILED_COUNTS = {**_SOURCE_COUNTS, "written": 1, "source_errors": 1}
_FANOUT_COUNTS = {**_SOURCE_COUNTS, "source_count": 1}


def _create_activity_error(cause: Exception) -> ActivityError:
    error = ActivityError(
        "Activity failed",
        scheduled_event_id=1,
        started_event_id=2,
        identity="worker",
        activity_type="sync_warehouse_account_properties_activity",
        activity_id="1",
        retry_state=None,
    )
    error.__cause__ = cause
    return error


def _staging_input() -> StageAccountPropertySyncInput:
    return StageAccountPropertySyncInput(
        team_id=7,
        saved_query_id="019f0000-0000-7000-8000-000000000001",
        job_id="job-1",
        table_uri="s3://data-warehouse/dlt/table",
        delta_version=5,
    )


def _segment_input() -> AccountPropertySyncInput:
    return AccountPropertySyncInput(
        team_id=7,
        saved_query_id="019f0000-0000-7000-8000-000000000001",
        job_id="job-1",
        segment="tracked",
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


@pytest.mark.parametrize(
    "fanout_enabled,workflow_name",
    [
        (False, "sync-warehouse-account-properties"),
        (True, "sync-warehouse-account-properties-fanout"),
    ],
)
async def test_dispatch_selects_one_workflow_type_and_keeps_stable_segment_ids(
    fanout_enabled: bool, workflow_name: str
) -> None:
    client = AsyncMock()
    client.start_workflow.side_effect = [WorkflowAlreadyStartedError("tracked", "workflow"), None]
    input = DispatchAccountPropertySyncInput(
        team_id=7,
        saved_query_id="019f0000-0000-7000-8000-000000000001",
        job_id="job-1",
    )

    with (
        patch(f"{_MODULE}.async_connect", return_value=client),
        patch(f"{_MODULE}.account_property_sync_fanout_enabled", return_value=fanout_enabled) as flag,
        patch(f"{_MODULE}.get_account_property_sync_source_concurrency", return_value=8) as concurrency_flag,
        patch(
            "products.customer_analytics.backend.logic.account_property_sync_monitoring.ph_background_capture"
        ) as capture_factory,
        patch(f"{_MODULE}.activity.info") as activity_info,
        patch(f"{_MODULE}.update_account_property_sync_runs_phase"),
    ):
        activity_info.return_value.attempt = 1
        activity_info.return_value.workflow_id = "stage-workflow-job-1"
        await dispatch_warehouse_account_property_sync_activity(input)

    flag.assert_called_once_with(7)
    calls = client.start_workflow.await_args_list
    assert [call.args[0] for call in calls] == [workflow_name, workflow_name]
    assert [call.args[1].segment for call in calls] == ["tracked", "ignored"]
    assert concurrency_flag.call_count == (1 if fanout_enabled else 0)
    expected_concurrency = 8 if fanout_enabled else 3
    assert [call.args[1].source_concurrency for call in calls] == [expected_concurrency, expected_concurrency]
    # Both workflow types share these IDs, so a retry after a flag change finds the running segment.
    assert [call.kwargs["id"] for call in calls] == [
        "sync-warehouse-account-properties-job-1-tracked",
        "sync-warehouse-account-properties-job-1-ignored",
    ]
    capture = capture_factory.return_value
    capture.assert_called_once()
    properties = capture.call_args.kwargs["properties"]
    assert {key: properties[key] for key in ("scope", "status", "path", "segment", "workflow_id")} == {
        "scope": "segment",
        "status": "started",
        "path": "fanout" if fanout_enabled else "legacy",
        "segment": "ignored",
        "workflow_id": "sync-warehouse-account-properties-job-1-ignored",
    }


@pytest.mark.parametrize(
    "telemetry_enabled,sync_result,expected_status,expected_counts",
    [
        (False, dict(_SOURCE_COUNTS), None, None),
        (True, dict(_SOURCE_COUNTS), "completed", _SOURCE_COUNTS),
        (True, {"rows_read": 0}, "completed", {"rows_read": 0}),
        (True, RuntimeError("sync failed"), "failed", None),
        (
            True,
            _create_activity_error(
                ApplicationError("Invalid values", _FAILED_COUNTS, type="AccountPropertySourceValueError")
            ),
            "failed",
            _FAILED_COUNTS,
        ),
    ],
)
async def test_legacy_workflow_reports_segment_outcome_only_after_the_patch(
    telemetry_enabled: bool,
    sync_result: object,
    expected_status: str | None,
    expected_counts: dict[str, int] | None,
) -> None:
    execute_activity = AsyncMock(side_effect=[sync_result, None])
    input = _segment_input()

    with (
        patch.object(workflow, "execute_activity", new=execute_activity),
        patch.object(workflow, "patched", return_value=telemetry_enabled),
        patch.object(workflow, "time", side_effect=[100.0, 160.0]),
    ):
        if isinstance(sync_result, Exception):
            with pytest.raises(type(sync_result)) as raised:
                await SyncWarehouseAccountPropertiesWorkflow().run(input)
            assert raised.value is sync_result
        else:
            await SyncWarehouseAccountPropertiesWorkflow().run(input)

    first_call = execute_activity.await_args_list[0]
    assert first_call.args == (sync_warehouse_account_properties_activity, input)
    assert first_call.kwargs["retry_policy"].maximum_attempts == 5
    if expected_status is None:
        assert execute_activity.await_count == 1
        return
    assert execute_activity.await_args_list[1].args[0] == emit_warehouse_account_property_segment_telemetry_activity
    telemetry = execute_activity.await_args_list[1].args[1]
    assert isinstance(telemetry, AccountPropertySegmentTelemetryInput)
    assert (telemetry.path, telemetry.status, telemetry.duration_seconds) == ("legacy", expected_status, 60.0)
    assert telemetry.counts == expected_counts
    assert telemetry.source_count == (None if expected_counts is None else expected_counts.get("source_count"))
    assert execute_activity.await_args_list[1].kwargs["schedule_to_close_timeout"] == timedelta(minutes=3)


@pytest.mark.parametrize("sync_failed", [False, True])
async def test_legacy_workflow_preserves_sync_outcome_when_telemetry_times_out(sync_failed: bool) -> None:
    sync_result = RuntimeError("Sync failed") if sync_failed else dict(_SOURCE_COUNTS)
    telemetry_error = _create_activity_error(
        TimeoutError("Telemetry timed out", type=TimeoutType.SCHEDULE_TO_CLOSE, last_heartbeat_details=[])
    )
    execute_activity = AsyncMock(side_effect=[sync_result, telemetry_error])

    with (
        patch.object(workflow, "execute_activity", new=execute_activity),
        patch.object(workflow, "patched", return_value=True),
        patch.object(workflow, "time", side_effect=[100.0, 160.0]),
        patch.object(workflow, "logger"),
    ):
        if sync_failed:
            with pytest.raises(RuntimeError, match="Sync failed"):
                await SyncWarehouseAccountPropertiesWorkflow().run(_segment_input())
        else:
            await SyncWarehouseAccountPropertiesWorkflow().run(_segment_input())


class _FakeFanoutActivities:
    def __init__(self, source_ids: list[str]) -> None:
        loop = asyncio.get_running_loop()
        self.source_ids = source_ids
        self.log: list[str] = []
        self.inputs: dict[str, object] = {}
        self.in_flight = 0
        self.max_in_flight = 0
        self.started = {source_id: asyncio.Event() for source_id in source_ids}
        self.results: dict[str, asyncio.Future[dict[str, int]]] = {
            source_id: loop.create_future() for source_id in source_ids
        }

    async def execute_activity(self, activity_fn: Callable[..., Any], arg: object, **_kwargs: object) -> object:
        if activity_fn is list_warehouse_account_property_sources_activity:
            return list(self.source_ids)
        if activity_fn is sync_warehouse_account_property_source_activity:
            assert isinstance(arg, AccountPropertySourceSyncInput)
            return await self._sync_source(arg.source_id)
        self.log.append(activity_fn.__name__)
        self.inputs[activity_fn.__name__] = arg
        return None

    async def _sync_source(self, source_id: str) -> dict[str, int]:
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        self.log.append(f"started:{source_id}")
        self.started[source_id].set()
        try:
            result = await self.results[source_id]
        except asyncio.CancelledError:
            self.log.append(f"cancelled:{source_id}")
            raise
        except Exception:
            self.log.append(f"failed:{source_id}")
            raise
        finally:
            self.in_flight -= 1
        self.log.append(f"completed:{source_id}")
        return result

    def started_sources(self) -> list[str]:
        return [entry.removeprefix("started:") for entry in self.log if entry.startswith("started:")]

    def telemetry(self) -> AccountPropertySegmentTelemetryInput:
        telemetry = self.inputs[emit_warehouse_account_property_segment_telemetry_activity.__name__]
        assert isinstance(telemetry, AccountPropertySegmentTelemetryInput)
        return telemetry


async def _wait(event: asyncio.Event) -> None:
    # Guards against a hang if the coordinator never starts the source. Correct runs never reach it.
    await asyncio.wait_for(event.wait(), timeout=5)


@pytest.mark.parametrize(
    "segment_input,cap",
    [
        (_segment_input(), 3),
        (dataclasses.replace(_segment_input(), source_concurrency=2), 2),
    ],
)
async def test_fanout_runs_sources_in_parallel_up_to_the_cap(segment_input: AccountPropertySyncInput, cap: int) -> None:
    source_ids = ["source-1", "source-2", "source-3", "source-4", "source-5"]
    fake = _FakeFanoutActivities(source_ids)

    with (
        patch.object(workflow, "execute_activity", new=fake.execute_activity),
        patch.object(workflow, "time", side_effect=[100.0, 145.0]),
    ):
        run = asyncio.create_task(SyncWarehouseAccountPropertiesFanoutWorkflow().run(segment_input))
        await _wait(fake.started[source_ids[cap - 1]])
        assert fake.started_sources() == source_ids[:cap]

        fake.results["source-2"].set_result(dict(_FANOUT_COUNTS))
        await _wait(fake.started[source_ids[cap]])
        assert fake.in_flight == cap
        assert fake.started_sources() == source_ids[: cap + 1]

        for source_id in source_ids:
            if not fake.results[source_id].done():
                fake.results[source_id].set_result(dict(_FANOUT_COUNTS))
        await asyncio.wait_for(run, timeout=5)

    assert fake.max_in_flight == cap
    complete = complete_warehouse_account_property_segment_activity.__name__
    assert fake.log.count(complete) == 1
    assert all(fake.log.index(f"completed:{source_id}") < fake.log.index(complete) for source_id in source_ids)
    telemetry = fake.telemetry()
    assert (telemetry.path, telemetry.status, telemetry.duration_seconds, telemetry.source_count) == (
        "fanout",
        "completed",
        45.0,
        5,
    )
    assert telemetry.counts == {
        "rows_read": 50,
        "changed": 20,
        "matched": 15,
        "written": 10,
        "source_errors": 0,
        "source_count": 5,
    }


async def test_fanout_waits_for_running_siblings_before_failing_the_segment() -> None:
    fake = _FakeFanoutActivities(["source-a", "source-b", "source-c"])
    fake.results["source-a"].set_result(dict(_FANOUT_COUNTS))
    fake.results["source-b"].set_exception(RuntimeError("source failed"))

    with (
        patch.object(workflow, "execute_activity", new=fake.execute_activity),
        patch.object(workflow, "time", return_value=100.0),
    ):
        run = asyncio.create_task(SyncWarehouseAccountPropertiesFanoutWorkflow().run(_segment_input()))
        await _wait(fake.started["source-c"])
        fake.results["source-c"].set_result(dict(_FANOUT_COUNTS))
        with pytest.raises(ApplicationError):
            await asyncio.wait_for(run, timeout=5)

    finalize = finalize_warehouse_account_property_runs_activity.__name__
    assert "cancelled:source-c" not in fake.log
    assert fake.log.index("completed:source-c") < fake.log.index(finalize)
    assert complete_warehouse_account_property_segment_activity.__name__ not in fake.log
    finalization = fake.inputs[finalize]
    assert isinstance(finalization, FinalizeAccountPropertySyncRunsInput)
    assert (finalization.status, finalization.segment) == ("failed", "tracked")
    telemetry = fake.telemetry()
    assert (telemetry.status, telemetry.source_count) == ("failed", 3)
    assert telemetry.counts == {
        "rows_read": 20,
        "changed": 8,
        "matched": 6,
        "written": 4,
        "source_errors": 1,
        "source_count": 2,
    }


async def test_fanout_finishes_a_segment_without_sources() -> None:
    fake = _FakeFanoutActivities([])

    with (
        patch.object(workflow, "execute_activity", new=fake.execute_activity),
        patch.object(workflow, "time", return_value=100.0),
    ):
        await SyncWarehouseAccountPropertiesFanoutWorkflow().run(_segment_input())

    assert fake.log == [
        complete_warehouse_account_property_segment_activity.__name__,
        emit_warehouse_account_property_segment_telemetry_activity.__name__,
    ]
    assert (fake.telemetry().status, fake.telemetry().source_count) == ("completed", 0)


async def test_fanout_cancellation_keeps_runs_open_and_reports_cancelled() -> None:
    fake = _FakeFanoutActivities(["source-a"])

    with (
        patch.object(workflow, "execute_activity", new=fake.execute_activity),
        patch.object(workflow, "time", return_value=100.0),
    ):
        run = asyncio.create_task(SyncWarehouseAccountPropertiesFanoutWorkflow().run(_segment_input()))
        await _wait(fake.started["source-a"])
        run.cancel()
        with pytest.raises(asyncio.CancelledError):
            await run

    assert finalize_warehouse_account_property_runs_activity.__name__ not in fake.log
    assert complete_warehouse_account_property_segment_activity.__name__ not in fake.log
    assert fake.telemetry().status == "cancelled"


async def test_fanout_workflow_retries_each_source_independently_and_replays() -> None:
    attempts: list[tuple[str, int]] = []
    completed: list[str] = []
    telemetry: list[AccountPropertySegmentTelemetryInput] = []

    @activity.defn(name="list-warehouse-account-property-sources")
    async def list_sources(_input: AccountPropertySyncInput) -> list[str]:
        return ["source-a", "source-b"]

    @activity.defn(name="sync-warehouse-account-property-source")
    async def sync_source(input: AccountPropertySourceSyncInput) -> dict[str, int]:
        attempt = activity.info().attempt
        attempts.append((input.source_id, attempt))
        if input.source_id == "source-a" and attempt == 1:
            raise RuntimeError("warehouse temporarily unavailable")
        return dict(_FANOUT_COUNTS)

    @activity.defn(name="complete-warehouse-account-property-segment")
    async def complete_segment(input: AccountPropertySyncInput) -> None:
        completed.append(input.segment)

    @activity.defn(name="finalize-warehouse-account-property-runs")
    async def finalize_runs(_input: FinalizeAccountPropertySyncRunsInput) -> None:
        raise AssertionError("A successful segment must not finalize runs as failed")

    @activity.defn(name="emit-warehouse-account-property-segment-telemetry")
    async def emit_telemetry(input: AccountPropertySegmentTelemetryInput) -> None:
        telemetry.append(input)

    fakes: list[Callable[..., Any]] = [list_sources, sync_source, complete_segment, finalize_runs, emit_telemetry]
    registered = {getattr(fn, "__temporal_activity_definition").name for fn in ACCOUNT_PROPERTY_SYNC_ACTIVITIES}
    assert {getattr(fn, "__temporal_activity_definition").name for fn in fakes} <= registered

    task_queue = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as environment:
        async with Worker(
            environment.client,
            task_queue=task_queue,
            workflows=ACCOUNT_PROPERTY_SYNC_WORKFLOWS,
            activities=fakes,
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            handle = await environment.client.start_workflow(
                SyncWarehouseAccountPropertiesFanoutWorkflow.run,
                _segment_input(),
                id=str(uuid.uuid4()),
                task_queue=task_queue,
                execution_timeout=timedelta(minutes=10),
            )
            await handle.result()
            history = await handle.fetch_history()

    await Replayer(
        workflows=[SyncWarehouseAccountPropertiesFanoutWorkflow], workflow_runner=UnsandboxedWorkflowRunner()
    ).replay_workflow(history)
    assert sorted(attempts) == [("source-a", 1), ("source-a", 2), ("source-b", 1)]
    assert completed == ["tracked"]
    assert [(event.status, event.source_count) for event in telemetry] == [("completed", 2)]


@workflow.defn(name=ACCOUNT_PROPERTY_SYNC_WORKFLOW_NAME)
class _PreTelemetrySyncWorkflow:
    @workflow.run
    async def run(self, input: AccountPropertySyncInput) -> None:
        await workflow.execute_activity(
            "sync_warehouse_account_properties_activity",
            input,
            start_to_close_timeout=timedelta(hours=6),
            heartbeat_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=5, initial_interval=timedelta(seconds=30)),
        )


@pytest.mark.parametrize("invalid_source_values", [False, True])
async def test_legacy_workflow_replays_histories_from_before_and_after_the_telemetry_patch(
    invalid_source_values: bool,
) -> None:
    telemetry_inputs: list[AccountPropertySegmentTelemetryInput] = []

    @activity.defn(name="sync_warehouse_account_properties_activity")
    async def sync_segment(_input: AccountPropertySyncInput) -> dict[str, int]:
        if invalid_source_values:
            raise ApplicationError(
                "Invalid values", _FAILED_COUNTS, type="AccountPropertySourceValueError", non_retryable=True
            )
        return dict(_SOURCE_COUNTS)

    @activity.defn(name="emit-warehouse-account-property-segment-telemetry")
    async def emit_telemetry(input: AccountPropertySegmentTelemetryInput) -> None:
        telemetry_inputs.append(input)

    scheduled_by_recorder: dict[str, list[str]] = {}
    async with await WorkflowEnvironment.start_time_skipping() as environment:
        for recorder in (_PreTelemetrySyncWorkflow, SyncWarehouseAccountPropertiesWorkflow):
            task_queue = str(uuid.uuid4())
            async with Worker(
                environment.client,
                task_queue=task_queue,
                workflows=[recorder],
                activities=[sync_segment, emit_telemetry],
                workflow_runner=UnsandboxedWorkflowRunner(),
            ):
                handle = await environment.client.start_workflow(
                    ACCOUNT_PROPERTY_SYNC_WORKFLOW_NAME,
                    _segment_input(),
                    id=str(uuid.uuid4()),
                    task_queue=task_queue,
                    execution_timeout=timedelta(minutes=10),
                )
                if invalid_source_values:
                    with pytest.raises(WorkflowFailureError):
                        await handle.result()
                else:
                    await handle.result()
                history = await handle.fetch_history()
            await Replayer(
                workflows=[SyncWarehouseAccountPropertiesWorkflow], workflow_runner=UnsandboxedWorkflowRunner()
            ).replay_workflow(history)
            scheduled_by_recorder[recorder.__name__] = [
                event.activity_task_scheduled_event_attributes.activity_type.name
                for event in history.events
                if event.HasField("activity_task_scheduled_event_attributes")
            ]

    assert len(telemetry_inputs) == 1
    assert telemetry_inputs[0].status == ("failed" if invalid_source_values else "completed")
    assert telemetry_inputs[0].counts == (_FAILED_COUNTS if invalid_source_values else _SOURCE_COUNTS)
    assert telemetry_inputs[0].source_count == 2
    assert scheduled_by_recorder == {
        "_PreTelemetrySyncWorkflow": ["sync_warehouse_account_properties_activity"],
        "SyncWarehouseAccountPropertiesWorkflow": [
            "sync_warehouse_account_properties_activity",
            "emit-warehouse-account-property-segment-telemetry",
        ],
    }


_ATTEMPT_OUTCOMES = [
    ("completed", dict(_SOURCE_COUNTS), "completed", None),
    ("transient_failure", RuntimeError("warehouse unavailable"), "failed", "RuntimeError"),
    (
        "invalid_values",
        AccountPropertySourceValueError("bad value", counts=_FAILED_COUNTS),
        "failed",
        "AccountPropertySourceValueError",
    ),
    ("cancelled", asyncio.CancelledError(), "cancelled", None),
]


@pytest.mark.parametrize(
    "path,activity_fn,runtime_target,activity_input,expected_source_id",
    [
        (
            "legacy",
            sync_warehouse_account_properties_activity,
            "run_account_property_segment_sync",
            _segment_input(),
            None,
        ),
        (
            "fanout",
            sync_warehouse_account_property_source_activity,
            "run_account_property_source_sync",
            AccountPropertySourceSyncInput(
                team_id=7,
                saved_query_id="019f0000-0000-7000-8000-000000000001",
                job_id="job-1",
                segment="tracked",
                source_id="019f0000-0000-7000-8000-0000000000aa",
            ),
            "019f0000-0000-7000-8000-0000000000aa",
        ),
    ],
)
@pytest.mark.parametrize("_outcome,runtime_result,expected_status,expected_error_type", _ATTEMPT_OUTCOMES)
async def test_sync_activity_reports_attempt_lifecycle(
    path: str,
    activity_fn: Callable[[Any], Any],
    runtime_target: str,
    activity_input: object,
    expected_source_id: str | None,
    _outcome: str,
    runtime_result: object,
    expected_status: str,
    expected_error_type: str | None,
) -> None:
    runtime = AsyncMock(side_effect=[runtime_result])

    with (
        patch(f"{_MODULE}.{runtime_target}", new=runtime),
        patch(f"{_MODULE}.capture_account_property_sync_event") as capture_event,
        patch(f"{_MODULE}.capture_exception"),
        patch(f"{_MODULE}.saved_query_binding"),
        patch(f"{_MODULE}.update_account_property_sync_runs_phase"),
        patch(f"{_MODULE}.Heartbeater", side_effect=lambda: _no_heartbeat()),
        patch(f"{_MODULE}.activity.info") as activity_info,
    ):
        activity_info.return_value.attempt = 2
        activity_info.return_value.workflow_id = "segment-workflow"
        activity_info.return_value.workflow_run_id = "segment-run"
        if isinstance(runtime_result, BaseException):
            with pytest.raises(BaseException) as raised:
                await activity_fn(activity_input)
            if isinstance(runtime_result, AccountPropertySourceValueError):
                assert isinstance(raised.value, ApplicationError) and raised.value.non_retryable
                assert raised.value.type == "AccountPropertySourceValueError"
                assert raised.value.details == (_FAILED_COUNTS,)
        else:
            assert await activity_fn(activity_input) == runtime_result

    events = [call.kwargs for call in capture_event.call_args_list]
    assert [event["status"] for event in events] == ["started", expected_status]
    assert {(event["path"], event["scope"], event["source_id"], event["attempt"]) for event in events} == {
        (path, "attempt", expected_source_id, 2)
    }
    assert events[1]["error_type"] == expected_error_type
    assert events[1]["duration_seconds"] is not None
    expected_counts = runtime_result if isinstance(runtime_result, dict) else None
    if isinstance(runtime_result, AccountPropertySourceValueError):
        expected_counts = _FAILED_COUNTS
    assert events[1]["counts"] == expected_counts
    assert events[1]["source_count"] == (None if expected_counts is None else expected_counts["source_count"])
