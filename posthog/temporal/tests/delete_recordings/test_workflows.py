import uuid
import asyncio
from datetime import datetime, timedelta

import pytest

import temporalio.worker
from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from posthog.session_recordings.session_recording_v2_service import RecordingBlock
from posthog.temporal.delete_recordings.activities import group_recording_blocks
from posthog.temporal.delete_recordings.types import (
    DeleteRecordingMetadataInput,
    Recording,
    RecordingBlockGroup,
    RecordingsWithPersonInput,
    RecordingsWithQueryInput,
    RecordingsWithTeamInput,
)
from posthog.temporal.delete_recordings.workflows import (
    DeleteRecordingMetadataWorkflow,
    DeleteRecordingsWithPersonWorkflow,
    DeleteRecordingsWithQueryWorkflow,
    DeleteRecordingsWithTeamWorkflow,
    DeleteRecordingWorkflow,
)


@pytest.mark.asyncio
async def test_delete_recording_workflow():
    TEST_SESSION_ID: str = "85a48e8a-9aa0-4628-ac5d-324266d35957"
    TEST_TEAM_ID: int = 12345
    TEST_SESSIONS = {
        TEST_SESSION_ID: [
            RecordingBlock(
                start_time=datetime.now(),
                end_time=datetime.now() + timedelta(hours=3),
                url="s3://test_bucket/session_recordings/1y/1756117652764-84b1bccb847e7ea6?range=bytes=12269307-12294780",
            ),
            RecordingBlock(
                start_time=datetime.now() + timedelta(hours=4),
                end_time=datetime.now() + timedelta(hours=6),
                url="s3://test_bucket/session_recordings/90d/1756117747546-97a0b1e81d492d3a?range=bytes=81788204-81793010",
            ),
            RecordingBlock(
                start_time=datetime.now() + timedelta(hours=4),
                end_time=datetime.now() + timedelta(hours=6),
                url="s3://test_bucket/session_recordings/90d/1756117747546-97a0b1e81d492d3a?range=bytes=2790658-2800843",
            ),
        ],
    }

    EXPECTED_GROUPED_RANGES = [
        [(12269307, 12294780)],
        [(81788204, 81793010), (2790658, 2800843)],
    ]

    EXPECTED_PATHS = [
        "session_recordings/1y/1756117652764-84b1bccb847e7ea6",
        "session_recordings/90d/1756117747546-97a0b1e81d492d3a",
    ]

    @activity.defn(name="load-recording-blocks")
    async def load_recording_blocks_mocked(input: Recording) -> list[RecordingBlock]:
        assert input.session_id == TEST_SESSION_ID
        assert input.team_id == TEST_TEAM_ID
        return TEST_SESSIONS[TEST_SESSION_ID]

    @activity.defn(name="delete-recording-blocks")
    async def delete_recording_blocks_mocked(input: RecordingBlockGroup) -> None:
        assert input.recording.session_id == TEST_SESSION_ID
        assert input.recording.team_id == TEST_TEAM_ID
        assert input.ranges in EXPECTED_GROUPED_RANGES
        assert input.path in EXPECTED_PATHS
        TEST_SESSIONS[input.recording.session_id] = []  # Delete recording blocks

    @activity.defn(name="schedule-recording-metadata-deletion")
    async def schedule_recording_metadata_deletion_mocked(input: Recording) -> None:
        assert input.session_id == TEST_SESSION_ID
        assert input.team_id == TEST_TEAM_ID

    @activity.defn(name="delete-recording-lts-data")
    async def delete_recording_lts_data_mocked(input: Recording) -> None:
        assert input.session_id == TEST_SESSION_ID
        assert input.team_id == TEST_TEAM_ID

    task_queue_name = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue_name,
            workflows=[DeleteRecordingWorkflow],
            activities=[
                load_recording_blocks_mocked,
                delete_recording_blocks_mocked,
                group_recording_blocks,
                schedule_recording_metadata_deletion_mocked,
                delete_recording_lts_data_mocked,
            ],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            await env.client.execute_workflow(
                DeleteRecordingWorkflow.run,
                Recording(session_id=TEST_SESSION_ID, team_id=TEST_TEAM_ID),
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
                url="s3://test_bucket/session_recordings/1y/1756117652764-84b1bccb847e7ea6?range=bytes=12269307-12294780",
            ),
            RecordingBlock(
                start_time=datetime.now() + timedelta(hours=4),
                end_time=datetime.now() + timedelta(hours=6),
                url="s3://test_bucket/session_recordings/90d/1756117747546-97a0b1e81d492d3a?range=bytes=81788204-81793010",
            ),
            RecordingBlock(
                start_time=datetime.now() + timedelta(hours=4),
                end_time=datetime.now() + timedelta(hours=6),
                url="s3://test_bucket/session_recordings/90d/1756117747546-97a0b1e81d492d3a?range=bytes=2790658-2800843",
            ),
        ],
        "791244f2-2569-4ed9-a448-d5a6e35471cd": [
            RecordingBlock(
                start_time=datetime.now(),
                end_time=datetime.now() + timedelta(hours=10),
                url="s3://test_bucket/session_recordings/5y/1756117699905-b688321ffa0fa994?range=bytes=12269307-12294780",
            ),
            RecordingBlock(
                start_time=datetime.now() + timedelta(hours=12),
                end_time=datetime.now() + timedelta(hours=14),
                url="s3://test_bucket/session_recordings/5y/1756117699905-b688321ffa0fa994?range=bytes=81788204-81793010",
            ),
        ],
        "3d2b505b-3a0e-48fd-89ab-6eb65a08e915": [
            RecordingBlock(
                start_time=datetime.now(),
                end_time=datetime.now() + timedelta(hours=23),
                url="s3://test_bucket/session_recordings/30d/1756117708699-28b991ee5019274d?range=bytes=81788204-81793010",
            ),
            RecordingBlock(
                start_time=datetime.now() + timedelta(hours=24),
                end_time=datetime.now() + timedelta(hours=26),
                url="s3://test_bucket/session_recordings/30d/1756117711878-61ed9e32ebf3e27a?range=bytes=2790658-2800843",
            ),
        ],
    }

    EXPECTED_GROUPED_RANGES = {
        "1c6c32da-0518-4a83-a513-eb2595c33b66": [
            [(12269307, 12294780)],
            [(81788204, 81793010), (2790658, 2800843)],
        ],
        "791244f2-2569-4ed9-a448-d5a6e35471cd": [
            [
                (12269307, 12294780),
                (81788204, 81793010),
            ],
        ],
        "3d2b505b-3a0e-48fd-89ab-6eb65a08e915": [
            [(81788204, 81793010)],
            [(2790658, 2800843)],
        ],
    }

    EXPECTED_PATHS = [
        "session_recordings/1y/1756117652764-84b1bccb847e7ea6",
        "session_recordings/90d/1756117747546-97a0b1e81d492d3a",
        "session_recordings/5y/1756117699905-b688321ffa0fa994",
        "session_recordings/30d/1756117708699-28b991ee5019274d",
        "session_recordings/30d/1756117711878-61ed9e32ebf3e27a",
    ]

    @activity.defn(name="load-recordings-with-person")
    async def load_recordings_with_person_mocked(input: RecordingsWithPersonInput) -> list[str]:
        assert input.distinct_ids == TEST_DISTINCT_IDS
        assert input.team_id == TEST_TEAM_ID
        return list(TEST_SESSIONS.keys())

    @activity.defn(name="load-recording-blocks")
    async def load_recording_blocks_mocked(input: Recording) -> list[RecordingBlock]:
        assert input.session_id in TEST_SESSIONS
        assert input.team_id == TEST_TEAM_ID
        return TEST_SESSIONS[input.session_id]

    @activity.defn(name="delete-recording-blocks")
    async def delete_recording_blocks_mocked(input: RecordingBlockGroup) -> None:
        assert input.recording.session_id in TEST_SESSIONS
        assert input.recording.team_id == TEST_TEAM_ID
        assert input.ranges in EXPECTED_GROUPED_RANGES[input.recording.session_id]
        assert input.path in EXPECTED_PATHS
        TEST_SESSIONS[input.recording.session_id] = []  # Delete recording blocks

    @activity.defn(name="schedule-recording-metadata-deletion")
    async def schedule_recording_metadata_deletion_mocked(input: Recording) -> None:
        assert input.session_id in TEST_SESSIONS
        assert input.team_id == TEST_TEAM_ID

    @activity.defn(name="delete-recording-lts-data")
    async def delete_recording_lts_data_mocked(input: Recording) -> None:
        assert input.session_id in TEST_SESSIONS
        assert input.team_id == TEST_TEAM_ID

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
                group_recording_blocks,
                schedule_recording_metadata_deletion_mocked,
                delete_recording_lts_data_mocked,
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


@pytest.mark.asyncio
async def test_delete_recordings_with_team_workflow():
    TEST_TEAM_ID: int = 99999
    TEST_SESSIONS = {
        "a1b2c3d4-e5f6-7890-abcd-ef1234567890": [
            RecordingBlock(
                start_time=datetime.now(),
                end_time=datetime.now() + timedelta(hours=2),
                url="s3://test_bucket/session_recordings/1y/1756117652764-84b1bccb847e7ea6?range=bytes=12269307-12294780",
            ),
            RecordingBlock(
                start_time=datetime.now() + timedelta(hours=3),
                end_time=datetime.now() + timedelta(hours=5),
                url="s3://test_bucket/session_recordings/90d/1756117747546-97a0b1e81d492d3a?range=bytes=81788204-81793010",
            ),
        ],
        "b2c3d4e5-f6g7-8901-bcde-f12345678901": [
            RecordingBlock(
                start_time=datetime.now(),
                end_time=datetime.now() + timedelta(hours=8),
                url="s3://test_bucket/session_recordings/5y/1756117699905-b688321ffa0fa994?range=bytes=12269307-12294780",
            ),
        ],
        "c3d4e5f6-g7h8-9012-cdef-123456789012": [
            RecordingBlock(
                start_time=datetime.now(),
                end_time=datetime.now() + timedelta(hours=15),
                url="s3://test_bucket/session_recordings/30d/1756117708699-28b991ee5019274d?range=bytes=81788204-81793010",
            ),
            RecordingBlock(
                start_time=datetime.now() + timedelta(hours=16),
                end_time=datetime.now() + timedelta(hours=18),
                url="s3://test_bucket/session_recordings/30d/1756117711878-61ed9e32ebf3e27a?range=bytes=2790658-2800843",
            ),
        ],
    }

    EXPECTED_GROUPED_RANGES = {
        "a1b2c3d4-e5f6-7890-abcd-ef1234567890": [
            [(12269307, 12294780)],
            [(81788204, 81793010)],
        ],
        "b2c3d4e5-f6g7-8901-bcde-f12345678901": [
            [(12269307, 12294780)],
        ],
        "c3d4e5f6-g7h8-9012-cdef-123456789012": [
            [(81788204, 81793010)],
            [(2790658, 2800843)],
        ],
    }

    EXPECTED_PATHS = [
        "session_recordings/1y/1756117652764-84b1bccb847e7ea6",
        "session_recordings/90d/1756117747546-97a0b1e81d492d3a",
        "session_recordings/5y/1756117699905-b688321ffa0fa994",
        "session_recordings/30d/1756117708699-28b991ee5019274d",
        "session_recordings/30d/1756117711878-61ed9e32ebf3e27a",
    ]

    @activity.defn(name="load-recordings-with-team-id")
    async def load_recordings_with_team_id_mocked(input: RecordingsWithTeamInput) -> list[str]:
        assert input.team_id == TEST_TEAM_ID
        return list(TEST_SESSIONS.keys())

    @activity.defn(name="load-recording-blocks")
    async def load_recording_blocks_mocked(input: Recording) -> list[RecordingBlock]:
        assert input.session_id in TEST_SESSIONS
        assert input.team_id == TEST_TEAM_ID
        return TEST_SESSIONS[input.session_id]

    @activity.defn(name="delete-recording-blocks")
    async def delete_recording_blocks_mocked(input: RecordingBlockGroup) -> None:
        assert input.recording.session_id in TEST_SESSIONS
        assert input.recording.team_id == TEST_TEAM_ID
        assert input.ranges in EXPECTED_GROUPED_RANGES[input.recording.session_id]
        assert input.path in EXPECTED_PATHS
        TEST_SESSIONS[input.recording.session_id] = []  # Delete recording blocks

    @activity.defn(name="schedule-recording-metadata-deletion")
    async def schedule_recording_metadata_deletion_mocked(input: Recording) -> None:
        assert input.session_id in TEST_SESSIONS
        assert input.team_id == TEST_TEAM_ID

    @activity.defn(name="delete-recording-lts-data")
    async def delete_recording_lts_data_mocked(input: Recording) -> None:
        assert input.session_id in TEST_SESSIONS
        assert input.team_id == TEST_TEAM_ID

    task_queue_name = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue_name,
            workflows=[DeleteRecordingsWithTeamWorkflow, DeleteRecordingWorkflow],
            activities=[
                load_recording_blocks_mocked,
                delete_recording_blocks_mocked,
                load_recordings_with_team_id_mocked,
                group_recording_blocks,
                schedule_recording_metadata_deletion_mocked,
                delete_recording_lts_data_mocked,
            ],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            parent_id = str(uuid.uuid4())

            await env.client.execute_workflow(
                DeleteRecordingsWithTeamWorkflow.run,
                RecordingsWithTeamInput(team_id=TEST_TEAM_ID),
                id=parent_id,
                task_queue=task_queue_name,
            )

            # Wait a short while to let child workflows complete
            await asyncio.sleep(3)

    # Check that all recording blocks were deleted
    assert TEST_SESSIONS == {
        "a1b2c3d4-e5f6-7890-abcd-ef1234567890": [],
        "b2c3d4e5-f6g7-8901-bcde-f12345678901": [],
        "c3d4e5f6-g7h8-9012-cdef-123456789012": [],
    }


@pytest.mark.asyncio
async def test_delete_recordings_with_query_workflow():
    TEST_QUERY = 'events=[{"id":"$pageview","type":"events"}]&date_from=-7d'
    TEST_TEAM_ID: int = 78901
    TEST_SESSIONS = {
        "4a1b2c3d-5e6f-7g8h-9i0j-1k2l3m4n5o6p": [
            RecordingBlock(
                start_time=datetime.now(),
                end_time=datetime.now() + timedelta(hours=1),
                url="s3://test_bucket/session_recordings/1y/1756117652764-84b1bccb847e7ea6?range=bytes=12269307-12294780",
            ),
            RecordingBlock(
                start_time=datetime.now() + timedelta(hours=2),
                end_time=datetime.now() + timedelta(hours=3),
                url="s3://test_bucket/session_recordings/90d/1756117747546-97a0b1e81d492d3a?range=bytes=81788204-81793010",
            ),
        ],
        "5b2c3d4e-6f7g-8h9i-0j1k-2l3m4n5o6p7q": [
            RecordingBlock(
                start_time=datetime.now(),
                end_time=datetime.now() + timedelta(hours=5),
                url="s3://test_bucket/session_recordings/5y/1756117699905-b688321ffa0fa994?range=bytes=12269307-12294780",
            ),
        ],
        "6c3d4e5f-7g8h-9i0j-1k2l-3m4n5o6p7q8r": [
            RecordingBlock(
                start_time=datetime.now(),
                end_time=datetime.now() + timedelta(hours=10),
                url="s3://test_bucket/session_recordings/30d/1756117708699-28b991ee5019274d?range=bytes=81788204-81793010",
            ),
            RecordingBlock(
                start_time=datetime.now() + timedelta(hours=11),
                end_time=datetime.now() + timedelta(hours=12),
                url="s3://test_bucket/session_recordings/30d/1756117711878-61ed9e32ebf3e27a?range=bytes=2790658-2800843",
            ),
        ],
    }

    EXPECTED_GROUPED_RANGES = {
        "4a1b2c3d-5e6f-7g8h-9i0j-1k2l3m4n5o6p": [
            [(12269307, 12294780)],
            [(81788204, 81793010)],
        ],
        "5b2c3d4e-6f7g-8h9i-0j1k-2l3m4n5o6p7q": [
            [(12269307, 12294780)],
        ],
        "6c3d4e5f-7g8h-9i0j-1k2l-3m4n5o6p7q8r": [
            [(81788204, 81793010)],
            [(2790658, 2800843)],
        ],
    }

    EXPECTED_PATHS = [
        "session_recordings/1y/1756117652764-84b1bccb847e7ea6",
        "session_recordings/90d/1756117747546-97a0b1e81d492d3a",
        "session_recordings/5y/1756117699905-b688321ffa0fa994",
        "session_recordings/30d/1756117708699-28b991ee5019274d",
        "session_recordings/30d/1756117711878-61ed9e32ebf3e27a",
    ]

    @activity.defn(name="load-recordings-with-query")
    async def load_recordings_with_query_mocked(input: RecordingsWithQueryInput) -> list[str]:
        assert input.query == TEST_QUERY
        assert input.team_id == TEST_TEAM_ID
        assert input.dry_run is False
        return list(TEST_SESSIONS.keys())

    @activity.defn(name="load-recording-blocks")
    async def load_recording_blocks_mocked(input: Recording) -> list[RecordingBlock]:
        assert input.session_id in TEST_SESSIONS
        assert input.team_id == TEST_TEAM_ID
        return TEST_SESSIONS[input.session_id]

    @activity.defn(name="delete-recording-blocks")
    async def delete_recording_blocks_mocked(input: RecordingBlockGroup) -> None:
        assert input.recording.session_id in TEST_SESSIONS
        assert input.recording.team_id == TEST_TEAM_ID
        assert input.ranges in EXPECTED_GROUPED_RANGES[input.recording.session_id]
        assert input.path in EXPECTED_PATHS
        TEST_SESSIONS[input.recording.session_id] = []  # Delete recording blocks

    @activity.defn(name="schedule-recording-metadata-deletion")
    async def schedule_recording_metadata_deletion_mocked(input: Recording) -> None:
        assert input.session_id in TEST_SESSIONS
        assert input.team_id == TEST_TEAM_ID

    @activity.defn(name="delete-recording-lts-data")
    async def delete_recording_lts_data_mocked(input: Recording) -> None:
        assert input.session_id in TEST_SESSIONS
        assert input.team_id == TEST_TEAM_ID

    task_queue_name = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue_name,
            workflows=[DeleteRecordingsWithQueryWorkflow, DeleteRecordingWorkflow],
            activities=[
                load_recording_blocks_mocked,
                delete_recording_blocks_mocked,
                load_recordings_with_query_mocked,
                group_recording_blocks,
                schedule_recording_metadata_deletion_mocked,
                delete_recording_lts_data_mocked,
            ],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            parent_id = str(uuid.uuid4())

            await env.client.execute_workflow(
                DeleteRecordingsWithQueryWorkflow.run,
                RecordingsWithQueryInput(query=TEST_QUERY, team_id=TEST_TEAM_ID, dry_run=False),
                id=parent_id,
                task_queue=task_queue_name,
            )

            # Wait a short while to let child workflows complete
            await asyncio.sleep(3)

    # Check that all recording blocks were deleted
    assert TEST_SESSIONS == {
        "4a1b2c3d-5e6f-7g8h-9i0j-1k2l3m4n5o6p": [],
        "5b2c3d4e-6f7g-8h9i-0j1k-2l3m4n5o6p7q": [],
        "6c3d4e5f-7g8h-9i0j-1k2l-3m4n5o6p7q8r": [],
    }


@pytest.mark.asyncio
async def test_delete_recordings_with_query_workflow_dry_run():
    TEST_QUERY = 'events=[{"id":"$pageview","type":"events"}]&date_from=-30d'
    TEST_TEAM_ID: int = 11111
    TEST_SESSIONS = {
        "7d4e5f6g-8h9i-0j1k-2l3m-4n5o6p7q8r9s": [
            RecordingBlock(
                start_time=datetime.now(),
                end_time=datetime.now() + timedelta(hours=1),
                url="s3://test_bucket/session_recordings/1y/1756117652764-84b1bccb847e7ea6?range=bytes=12269307-12294780",
            ),
        ],
        "8e5f6g7h-9i0j-1k2l-3m4n-5o6p7q8r9s0t": [
            RecordingBlock(
                start_time=datetime.now(),
                end_time=datetime.now() + timedelta(hours=2),
                url="s3://test_bucket/session_recordings/90d/1756117747546-97a0b1e81d492d3a?range=bytes=81788204-81793010",
            ),
        ],
    }

    @activity.defn(name="load-recordings-with-query")
    async def load_recordings_with_query_mocked(input: RecordingsWithQueryInput) -> list[str]:
        assert input.query == TEST_QUERY
        assert input.team_id == TEST_TEAM_ID
        assert input.dry_run is True
        return list(TEST_SESSIONS.keys())

    @activity.defn(name="load-recording-blocks")
    async def load_recording_blocks_mocked(input: Recording) -> list[RecordingBlock]:
        raise AssertionError("Should not be called in dry run mode")

    @activity.defn(name="delete-recording-blocks")
    async def delete_recording_blocks_mocked(input: RecordingBlockGroup) -> None:
        raise AssertionError("Should not be called in dry run mode")

    @activity.defn(name="schedule-recording-metadata-deletion")
    async def schedule_recording_metadata_deletion_mocked(input: Recording) -> None:
        raise AssertionError("Should not be called in dry run mode")

    @activity.defn(name="delete-recording-lts-data")
    async def delete_recording_lts_data_mocked(input: Recording) -> None:
        raise AssertionError("Should not be called in dry run mode")

    task_queue_name = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue_name,
            workflows=[DeleteRecordingsWithQueryWorkflow, DeleteRecordingWorkflow],
            activities=[
                load_recording_blocks_mocked,
                delete_recording_blocks_mocked,
                load_recordings_with_query_mocked,
                group_recording_blocks,
                schedule_recording_metadata_deletion_mocked,
                delete_recording_lts_data_mocked,
            ],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            parent_id = str(uuid.uuid4())

            await env.client.execute_workflow(
                DeleteRecordingsWithQueryWorkflow.run,
                RecordingsWithQueryInput(query=TEST_QUERY, team_id=TEST_TEAM_ID, dry_run=True),
                id=parent_id,
                task_queue=task_queue_name,
            )

            # Wait a short while to ensure no child workflows were started
            await asyncio.sleep(1)

    # Check that no recording blocks were deleted in dry run mode
    assert len(TEST_SESSIONS["7d4e5f6g-8h9i-0j1k-2l3m-4n5o6p7q8r9s"]) == 1
    assert len(TEST_SESSIONS["8e5f6g7h-9i0j-1k2l-3m4n-5o6p7q8r9s0t"]) == 1
    assert (
        TEST_SESSIONS["7d4e5f6g-8h9i-0j1k-2l3m-4n5o6p7q8r9s"][0].url
        == "s3://test_bucket/session_recordings/1y/1756117652764-84b1bccb847e7ea6?range=bytes=12269307-12294780"
    )
    assert (
        TEST_SESSIONS["8e5f6g7h-9i0j-1k2l-3m4n-5o6p7q8r9s0t"][0].url
        == "s3://test_bucket/session_recordings/90d/1756117747546-97a0b1e81d492d3a?range=bytes=81788204-81793010"
    )


@pytest.mark.asyncio
async def test_delete_recording_metadata_workflow():
    activity_called = False

    @activity.defn(name="perform-recording-metadata-deletion")
    async def perform_recording_metadata_deletion_mocked(input: DeleteRecordingMetadataInput) -> None:
        nonlocal activity_called
        activity_called = True
        assert input.dry_run is False

    task_queue_name = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue_name,
            workflows=[DeleteRecordingMetadataWorkflow],
            activities=[perform_recording_metadata_deletion_mocked],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            await env.client.execute_workflow(
                DeleteRecordingMetadataWorkflow.run,
                DeleteRecordingMetadataInput(dry_run=False),
                id=str(uuid.uuid4()),
                task_queue=task_queue_name,
            )

    assert activity_called is True


@pytest.mark.asyncio
async def test_delete_recording_metadata_workflow_dry_run():
    activity_called = False

    @activity.defn(name="perform-recording-metadata-deletion")
    async def perform_recording_metadata_deletion_mocked(input: DeleteRecordingMetadataInput) -> None:
        nonlocal activity_called
        activity_called = True
        assert input.dry_run is True

    task_queue_name = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue_name,
            workflows=[DeleteRecordingMetadataWorkflow],
            activities=[perform_recording_metadata_deletion_mocked],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            await env.client.execute_workflow(
                DeleteRecordingMetadataWorkflow.run,
                DeleteRecordingMetadataInput(dry_run=True),
                id=str(uuid.uuid4()),
                task_queue=task_queue_name,
            )

    assert activity_called is True


def test_delete_recording_metadata_workflow_parse_inputs():
    result = DeleteRecordingMetadataWorkflow.parse_inputs(['{"dry_run": true}'])
    assert result.dry_run is True

    result = DeleteRecordingMetadataWorkflow.parse_inputs(['{"dry_run": false}'])
    assert result.dry_run is False

    result = DeleteRecordingMetadataWorkflow.parse_inputs(["{}"])
    assert result.dry_run is False


@pytest.mark.asyncio
async def test_delete_recording_workflow_no_blocks():
    """Test that workflow handles recordings with no blocks gracefully."""
    TEST_SESSION_ID: str = "empty-session-id"
    TEST_TEAM_ID: int = 55555
    lts_deleted = False
    metadata_scheduled = False

    @activity.defn(name="load-recording-blocks")
    async def load_recording_blocks_mocked(input: Recording) -> list[RecordingBlock]:
        assert input.session_id == TEST_SESSION_ID
        assert input.team_id == TEST_TEAM_ID
        return []  # No blocks

    @activity.defn(name="delete-recording-blocks")
    async def delete_recording_blocks_mocked(input: RecordingBlockGroup) -> None:
        raise AssertionError("Should not be called when there are no blocks")

    @activity.defn(name="schedule-recording-metadata-deletion")
    async def schedule_recording_metadata_deletion_mocked(input: Recording) -> None:
        nonlocal metadata_scheduled
        metadata_scheduled = True
        assert input.session_id == TEST_SESSION_ID
        assert input.team_id == TEST_TEAM_ID

    @activity.defn(name="delete-recording-lts-data")
    async def delete_recording_lts_data_mocked(input: Recording) -> None:
        nonlocal lts_deleted
        lts_deleted = True
        assert input.session_id == TEST_SESSION_ID
        assert input.team_id == TEST_TEAM_ID

    task_queue_name = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue_name,
            workflows=[DeleteRecordingWorkflow],
            activities=[
                load_recording_blocks_mocked,
                delete_recording_blocks_mocked,
                group_recording_blocks,
                schedule_recording_metadata_deletion_mocked,
                delete_recording_lts_data_mocked,
            ],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            await env.client.execute_workflow(
                DeleteRecordingWorkflow.run,
                Recording(session_id=TEST_SESSION_ID, team_id=TEST_TEAM_ID),
                id=str(uuid.uuid4()),
                task_queue=task_queue_name,
            )

    # Even with no blocks, LTS and metadata cleanup should still happen
    assert lts_deleted is True
    assert metadata_scheduled is True


@pytest.mark.asyncio
async def test_delete_recordings_with_team_workflow_dry_run():
    """Test that dry run mode loads sessions but doesn't delete anything."""
    TEST_TEAM_ID: int = 44444
    TEST_SESSIONS = {
        "dry-run-session-1": [
            RecordingBlock(
                start_time=datetime.now(),
                end_time=datetime.now() + timedelta(hours=1),
                url="s3://test_bucket/session_recordings/1y/test-file?range=bytes=0-1000",
            ),
        ],
        "dry-run-session-2": [
            RecordingBlock(
                start_time=datetime.now(),
                end_time=datetime.now() + timedelta(hours=2),
                url="s3://test_bucket/session_recordings/90d/test-file2?range=bytes=0-2000",
            ),
        ],
    }

    @activity.defn(name="load-recordings-with-team-id")
    async def load_recordings_with_team_id_mocked(input: RecordingsWithTeamInput) -> list[str]:
        assert input.team_id == TEST_TEAM_ID
        assert input.dry_run is True
        return list(TEST_SESSIONS.keys())

    @activity.defn(name="load-recording-blocks")
    async def load_recording_blocks_mocked(input: Recording) -> list[RecordingBlock]:
        raise AssertionError("Should not be called in dry run mode")

    @activity.defn(name="delete-recording-blocks")
    async def delete_recording_blocks_mocked(input: RecordingBlockGroup) -> None:
        raise AssertionError("Should not be called in dry run mode")

    @activity.defn(name="schedule-recording-metadata-deletion")
    async def schedule_recording_metadata_deletion_mocked(input: Recording) -> None:
        raise AssertionError("Should not be called in dry run mode")

    @activity.defn(name="delete-recording-lts-data")
    async def delete_recording_lts_data_mocked(input: Recording) -> None:
        raise AssertionError("Should not be called in dry run mode")

    task_queue_name = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue_name,
            workflows=[DeleteRecordingsWithTeamWorkflow, DeleteRecordingWorkflow],
            activities=[
                load_recording_blocks_mocked,
                delete_recording_blocks_mocked,
                load_recordings_with_team_id_mocked,
                group_recording_blocks,
                schedule_recording_metadata_deletion_mocked,
                delete_recording_lts_data_mocked,
            ],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            parent_id = str(uuid.uuid4())

            await env.client.execute_workflow(
                DeleteRecordingsWithTeamWorkflow.run,
                RecordingsWithTeamInput(team_id=TEST_TEAM_ID, dry_run=True),
                id=parent_id,
                task_queue=task_queue_name,
            )

            # Wait a short while to ensure no child workflows were started
            await asyncio.sleep(1)

    # Check that no recording blocks were deleted in dry run mode
    assert len(TEST_SESSIONS["dry-run-session-1"]) == 1
    assert len(TEST_SESSIONS["dry-run-session-2"]) == 1
