import uuid
from uuid import UUID

import pytest

import temporalio.worker
from temporalio import activity
from temporalio.client import WorkflowFailureError
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from posthog.temporal.session_replay.export_recording.types import (
    ExportContext,
    ExportRecordingInput,
    MarkExportFailedInput,
)
from posthog.temporal.session_replay.export_recording.workflow import ExportRecordingWorkflow


def test_export_recording_workflow_parse_inputs():
    result = ExportRecordingWorkflow.parse_inputs(['{"exported_recording_id": "01938a67-1234-7000-8000-000000000001"}'])
    assert result.exported_recording_id == UUID("01938a67-1234-7000-8000-000000000001")
    assert result.redis_config.redis_url is None


def test_export_recording_workflow_parse_inputs_string_uuid():
    result = ExportRecordingWorkflow.parse_inputs(['{"exported_recording_id": "01938a67-5678-7000-8000-000000000002"}'])
    assert result.exported_recording_id == UUID("01938a67-5678-7000-8000-000000000002")


def test_export_recording_workflow_parse_inputs_with_redis_config():
    result = ExportRecordingWorkflow.parse_inputs(
        [
            '{"exported_recording_id": "01938a67-1234-7000-8000-000000000001", '
            '"redis_config": {"redis_url": "redis://custom-redis:6380", "redis_ttl": 7200}}'
        ]
    )
    assert result.exported_recording_id == UUID("01938a67-1234-7000-8000-000000000001")
    assert result.redis_config.redis_url == "redis://custom-redis:6380"
    assert result.redis_config.redis_ttl == 7200


@pytest.mark.asyncio
async def test_export_recording_workflow_marks_failed_on_activity_error():
    recording_id = UUID("01938a67-1234-7000-8000-000000000099")
    marked: list[MarkExportFailedInput] = []

    @activity.defn(name="build_recording_export_context")
    async def build_mocked(input: ExportRecordingInput) -> ExportContext:
        return ExportContext(
            export_id=uuid.uuid4(),
            exported_recording_id=input.exported_recording_id,
            session_id="test-session",
            team_id=1,
            redis_config=input.redis_config,
        )

    # mimic the real failure: a ClickHouse error in one of the parallel activities
    @activity.defn(name="export_event_clickhouse_rows")
    async def event_rows_failing(input: ExportContext) -> None:
        raise ApplicationError("no column 'sharded_events.properties_group_ai_large'", non_retryable=True)

    @activity.defn(name="export_replay_clickhouse_rows")
    async def noop_replay(input: ExportContext) -> None: ...

    @activity.defn(name="export_recording_data")
    async def noop_data(input: ExportContext) -> None: ...

    @activity.defn(name="export_recording_data_prefix")
    async def noop_prefix(input: ExportContext) -> None: ...

    @activity.defn(name="store_export_data")
    async def noop_store(input: ExportContext) -> None: ...

    @activity.defn(name="cleanup_export_data")
    async def noop_cleanup(input: ExportContext) -> None: ...

    @activity.defn(name="mark_export_failed")
    async def mark_failed_mocked(input: MarkExportFailedInput) -> None:
        marked.append(input)

    task_queue_name = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue_name,
            workflows=[ExportRecordingWorkflow],
            activities=[
                build_mocked,
                event_rows_failing,
                noop_replay,
                noop_data,
                noop_prefix,
                noop_store,
                noop_cleanup,
                mark_failed_mocked,
            ],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            with pytest.raises(WorkflowFailureError):
                await env.client.execute_workflow(
                    ExportRecordingWorkflow.run,
                    ExportRecordingInput(exported_recording_id=recording_id),
                    id=str(uuid.uuid4()),
                    task_queue=task_queue_name,
                )

    # the export is marked failed (not left RUNNING) with a non-empty error recorded
    assert len(marked) == 1
    assert marked[0].exported_recording_id == recording_id
    assert marked[0].error_message


@pytest.mark.asyncio
async def test_export_recording_workflow_reraises_original_when_marking_also_fails():
    recording_id = UUID("01938a67-1234-7000-8000-000000000098")

    @activity.defn(name="build_recording_export_context")
    async def build_mocked(input: ExportRecordingInput) -> ExportContext:
        return ExportContext(
            export_id=uuid.uuid4(),
            exported_recording_id=input.exported_recording_id,
            session_id="test-session",
            team_id=1,
            redis_config=input.redis_config,
        )

    @activity.defn(name="export_event_clickhouse_rows")
    async def event_rows_failing(input: ExportContext) -> None:
        raise ApplicationError("original export error", non_retryable=True)

    @activity.defn(name="export_replay_clickhouse_rows")
    async def noop_replay(input: ExportContext) -> None: ...

    @activity.defn(name="export_recording_data")
    async def noop_data(input: ExportContext) -> None: ...

    @activity.defn(name="export_recording_data_prefix")
    async def noop_prefix(input: ExportContext) -> None: ...

    @activity.defn(name="store_export_data")
    async def noop_store(input: ExportContext) -> None: ...

    @activity.defn(name="cleanup_export_data")
    async def noop_cleanup(input: ExportContext) -> None: ...

    # the failure handler itself fails (e.g. DB unreachable) - this must not mask the original error
    @activity.defn(name="mark_export_failed")
    async def mark_failed_failing(input: MarkExportFailedInput) -> None:
        raise ApplicationError("could not reach the database", non_retryable=True)

    task_queue_name = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue_name,
            workflows=[ExportRecordingWorkflow],
            activities=[
                build_mocked,
                event_rows_failing,
                noop_replay,
                noop_data,
                noop_prefix,
                noop_store,
                noop_cleanup,
                mark_failed_failing,
            ],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            with pytest.raises(WorkflowFailureError) as exc_info:
                await env.client.execute_workflow(
                    ExportRecordingWorkflow.run,
                    ExportRecordingInput(exported_recording_id=recording_id),
                    id=str(uuid.uuid4()),
                    task_queue=task_queue_name,
                )

    # the workflow still fails on the original export error, not the secondary marking failure
    assert "could not reach the database" not in str(exc_info.value)
