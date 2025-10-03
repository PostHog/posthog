import uuid
import asyncio
from datetime import datetime, timedelta

import pytest

import temporalio.worker
from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from posthog.session_recordings.session_recording_v2_service import RecordingBlock
from posthog.temporal.delete_recordings.types import (
    DeleteRecordingBlocksInput,
    RecordingInput,
    RecordingsWithPersonInput,
)
from posthog.temporal.delete_recordings.workflows import DeleteRecordingsWithPersonWorkflow, DeleteRecordingWorkflow


@pytest.mark.asyncio
async def test_delete_recording_workflow():
    TEST_SESSION_ID: str = "85a48e8a-9aa0-4628-ac5d-324266d35957"
    TEST_TEAM_ID: int = 12345
    TEST_SESSIONS = {
        TEST_SESSION_ID: [
            RecordingBlock(
                start_time=datetime.now(),
                end_time=datetime.now() + timedelta(hours=3),
                url="s3://test_bucket/session_recordings/1y/1756117652764-84b1bccb847e7ea6",
            ),
            RecordingBlock(
                start_time=datetime.now() + timedelta(hours=4),
                end_time=datetime.now() + timedelta(hours=6),
                url="s3://test_bucket/session_recordings/90d/1756117747546-97a0b1e81d492d3a",
            ),
        ],
    }

    @activity.defn(name="load-recording-blocks")
    async def load_recording_blocks_mocked(input: RecordingInput) -> list[RecordingBlock]:
        assert input.session_id == TEST_SESSION_ID
        assert input.team_id == TEST_TEAM_ID
        return TEST_SESSIONS[TEST_SESSION_ID]

    @activity.defn(name="delete-recording-blocks")
    async def delete_recording_blocks_mocked(input: DeleteRecordingBlocksInput) -> None:
        assert input.recording.session_id == TEST_SESSION_ID
        assert input.recording.team_id == TEST_TEAM_ID
        assert input.blocks == TEST_SESSIONS[TEST_SESSION_ID]
        TEST_SESSIONS[input.recording.session_id] = []  # Delete recording blocks

    task_queue_name = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue_name,
            workflows=[DeleteRecordingWorkflow],
            activities=[load_recording_blocks_mocked, delete_recording_blocks_mocked],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            await env.client.execute_workflow(
                DeleteRecordingWorkflow.run,
                RecordingInput(session_id=TEST_SESSION_ID, team_id=TEST_TEAM_ID),
                id=str(uuid.uuid4()),
                task_queue=task_queue_name,
            )

    # Check that all recording blocks were deleted
    assert TEST_SESSIONS == {TEST_SESSION_ID: []}


@pytest.mark.asyncio
async def test_delete_recording_with_person_workflow():
    TEST_DISTINCT_IDS = ["5e0c4450-704f-4c9f-aa55-576a6b5d4d0f", "1e6f00d7-2df1-4991-a33b-764c2c086f1c"]
    TEST_TEAM_ID: int = 45678
    TEST_SESSIONS = {
        "1c6c32da-0518-4a83-a513-eb2595c33b66": [
            RecordingBlock(
                start_time=datetime.now(),
                end_time=datetime.now() + timedelta(hours=3),
                url="s3://test_bucket/session_recordings/1y/1756117652764-84b1bccb847e7ea6",
            ),
            RecordingBlock(
                start_time=datetime.now() + timedelta(hours=4),
                end_time=datetime.now() + timedelta(hours=6),
                url="s3://test_bucket/session_recordings/90d/1756117747546-97a0b1e81d492d3a",
            ),
        ],
        "791244f2-2569-4ed9-a448-d5a6e35471cd": [
            RecordingBlock(
                start_time=datetime.now(),
                end_time=datetime.now() + timedelta(hours=10),
                url="s3://test_bucket/session_recordings/5y/1756117699905-b688321ffa0fa994",
            ),
            RecordingBlock(
                start_time=datetime.now() + timedelta(hours=12),
                end_time=datetime.now() + timedelta(hours=14),
                url="s3://test_bucket/session_recordings/90d/1756117702805-183ced947c057852",
            ),
        ],
        "3d2b505b-3a0e-48fd-89ab-6eb65a08e915": [
            RecordingBlock(
                start_time=datetime.now(),
                end_time=datetime.now() + timedelta(hours=23),
                url="s3://test_bucket/session_recordings/30d/1756117708699-28b991ee5019274d",
            ),
            RecordingBlock(
                start_time=datetime.now() + timedelta(hours=24),
                end_time=datetime.now() + timedelta(hours=26),
                url="s3://test_bucket/session_recordings/30d/1756117711878-61ed9e32ebf3e27a",
            ),
        ],
    }

    @activity.defn(name="load-recordings-with-person")
    async def load_recordings_with_person_mocked(input: RecordingsWithPersonInput) -> list[str]:
        assert input.distinct_ids == TEST_DISTINCT_IDS
        assert input.team_id == TEST_TEAM_ID
        return list(TEST_SESSIONS.keys())

    @activity.defn(name="load-recording-blocks")
    async def load_recording_blocks_mocked(input: RecordingInput) -> list[RecordingBlock]:
        assert input.session_id in TEST_SESSIONS
        assert input.team_id == TEST_TEAM_ID
        return TEST_SESSIONS[input.session_id]

    @activity.defn(name="delete-recording-blocks")
    async def delete_recording_blocks_mocked(input: DeleteRecordingBlocksInput) -> None:
        assert input.recording.session_id in TEST_SESSIONS
        assert input.recording.team_id == TEST_TEAM_ID
        assert input.blocks == TEST_SESSIONS[input.recording.session_id]
        TEST_SESSIONS[input.recording.session_id] = []  # Delete recording blocks

    task_queue_name = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue_name,
            workflows=[DeleteRecordingsWithPersonWorkflow, DeleteRecordingWorkflow],
            activities=[
                load_recording_blocks_mocked,
                delete_recording_blocks_mocked,
                load_recordings_with_person_mocked,
            ],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            parent_id = str(uuid.uuid4())

            await env.client.execute_workflow(
                DeleteRecordingsWithPersonWorkflow.run,
                RecordingsWithPersonInput(distinct_ids=TEST_DISTINCT_IDS, team_id=TEST_TEAM_ID),
                id=parent_id,
                task_queue=task_queue_name,
            )

            # Wait a short while to let child workflows complete
            await asyncio.sleep(3)

    # Check that all recording blocks were deleted
    assert TEST_SESSIONS == {
        "1c6c32da-0518-4a83-a513-eb2595c33b66": [],
        "791244f2-2569-4ed9-a448-d5a6e35471cd": [],
        "3d2b505b-3a0e-48fd-89ab-6eb65a08e915": [],
    }
