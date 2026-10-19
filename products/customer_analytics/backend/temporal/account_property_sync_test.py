import uuid
import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta

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
    DispatchAccountPropertySyncInput,
    FinalizeAccountPropertySyncRunsInput,
    StageAccountPropertySyncInput,
)
from products.customer_analytics.backend.logic.account_property_sync import AccountPropertySourceValueError
from products.customer_analytics.backend.temporal.account_property_sync import (
    ACCOUNT_PROPERTY_SYNC_WORKFLOW_NAME,
    AccountPropertySyncInput,
    StageWarehouseAccountPropertiesWorkflow,
    SyncWarehouseAccountPropertiesWorkflow,
    dispatch_warehouse_account_property_sync_activity,
    emit_warehouse_account_property_segment_telemetry_activity,
    finalize_warehouse_account_property_runs_activity,
    stage_warehouse_account_property_files_activity,
    start_warehouse_account_property_runs_activity,
    sync_warehouse_account_properties_activity,
)

pytestmark = pytest.mark.asyncio

_MODULE = "products.customer_analytics.backend.temporal.account_property_sync"
_SOURCE_COUNTS = {"rows_read": 10, "changed": 4, "matched": 3, "written": 2, "source_errors": 0, "source_count": 2}
_FAILED_COUNTS = {**_SOURCE_COUNTS, "written": 1, "source_errors": 1}


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
        patch(
            "products.customer_analytics.backend.logic.account_property_sync_monitoring.ph_background_capture"
        ) as capture_factory,
    ):
        activity_info.return_value.attempt = 1
        activity_info.return_value.workflow_id = "stage-workflow-job-1"
        await dispatch_warehouse_account_property_sync_activity(input)

    calls = client.start_workflow.await_args_list
    assert [call.args[0] for call in calls] == [
        ACCOUNT_PROPERTY_SYNC_WORKFLOW_NAME,
        ACCOUNT_PROPERTY_SYNC_WORKFLOW_NAME,
    ]
    assert [call.args[1].segment for call in calls] == ["tracked", "ignored"]
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
        "path": "legacy",
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


@pytest.mark.parametrize(
    "runtime_result,expected_status,expected_error_type",
    [
        (dict(_SOURCE_COUNTS), "completed", None),
        (RuntimeError("warehouse unavailable"), "failed", "RuntimeError"),
        (
            AccountPropertySourceValueError("bad value", counts=_FAILED_COUNTS),
            "failed",
            "AccountPropertySourceValueError",
        ),
        (asyncio.CancelledError(), "cancelled", None),
    ],
)
async def test_sync_activity_reports_attempt_lifecycle(
    runtime_result: object, expected_status: str, expected_error_type: str | None
) -> None:
    runtime = AsyncMock(side_effect=[runtime_result])

    with (
        patch(f"{_MODULE}.run_account_property_segment_sync", new=runtime),
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
                await sync_warehouse_account_properties_activity(_segment_input())
            if isinstance(runtime_result, AccountPropertySourceValueError):
                assert isinstance(raised.value, ApplicationError) and raised.value.non_retryable
                assert raised.value.type == "AccountPropertySourceValueError"
                assert raised.value.details == (_FAILED_COUNTS,)
        else:
            assert await sync_warehouse_account_properties_activity(_segment_input()) == runtime_result

    events = [call.kwargs for call in capture_event.call_args_list]
    assert [event["status"] for event in events] == ["started", expected_status]
    assert {(event["path"], event["scope"], event["source_id"], event["attempt"]) for event in events} == {
        ("legacy", "attempt", None, 2)
    }
    assert events[1]["error_type"] == expected_error_type
    assert events[1]["duration_seconds"] is not None
    expected_counts = runtime_result if isinstance(runtime_result, dict) else None
    if isinstance(runtime_result, AccountPropertySourceValueError):
        expected_counts = _FAILED_COUNTS
    assert events[1]["counts"] == expected_counts
    assert events[1]["source_count"] == (None if expected_counts is None else expected_counts["source_count"])
