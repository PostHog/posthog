import uuid

import pytest
from unittest.mock import AsyncMock, patch

import temporalio.worker
from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from posthog.temporal.delete_recordings.types import (
    BulkDeleteInput,
    BulkDeleteResult,
    DeletionCertificate,
    DeletionConfig,
    LoadRecordingsPage,
    PurgeDeletedMetadataInput,
    PurgeDeletedMetadataResult,
    RecordingsWithPersonInput,
    RecordingsWithQueryInput,
    RecordingsWithSessionIdsInput,
    RecordingsWithTeamInput,
)
from posthog.temporal.delete_recordings.workflows import (
    DeleteRecordingsWithPersonWorkflow,
    DeleteRecordingsWithQueryWorkflow,
    DeleteRecordingsWithSessionIdsWorkflow,
    DeleteRecordingsWithTeamWorkflow,
    PurgeDeletedRecordingMetadataWorkflow,
)


@pytest.mark.asyncio
async def test_delete_recordings_with_person_workflow():
    TEST_DISTINCT_IDS = ["5e0c4450-704f-4c9f-aa55-576a6b5d4d0f", "1e6f00d7-2df1-4991-a33b-764c2c086f1c"]
    TEST_TEAM_ID: int = 45678
    TEST_SESSION_IDS = [
        "1c6c32da-0518-4a83-a513-eb2595c33b66",
        "791244f2-2569-4ed9-a448-d5a6e35471cd",
        "3d2b505b-3a0e-48fd-89ab-6eb65a08e915",
    ]

    deleted_sessions: list[str] = []

    @activity.defn(name="load-recordings-with-person")
    async def load_recordings_with_person_mocked(input: RecordingsWithPersonInput) -> LoadRecordingsPage:
        assert input.distinct_ids == TEST_DISTINCT_IDS
        assert input.team_id == TEST_TEAM_ID
        return LoadRecordingsPage(session_ids=TEST_SESSION_IDS, next_cursor=None)

    @activity.defn(name="bulk-delete-recordings")
    async def bulk_delete_recordings_mocked(input: BulkDeleteInput) -> BulkDeleteResult:
        assert input.team_id == TEST_TEAM_ID
        deleted_sessions.extend(input.session_ids)
        return BulkDeleteResult(deleted=input.session_ids)

    task_queue_name = str(uuid.uuid4())
    workflow_id = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue_name,
            workflows=[DeleteRecordingsWithPersonWorkflow],
            activities=[
                load_recordings_with_person_mocked,
                bulk_delete_recordings_mocked,
            ],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            result = await env.client.execute_workflow(
                DeleteRecordingsWithPersonWorkflow.run,
                RecordingsWithPersonInput(distinct_ids=TEST_DISTINCT_IDS, team_id=TEST_TEAM_ID),
                id=workflow_id,
                task_queue=task_queue_name,
            )

    assert sorted(deleted_sessions) == sorted(TEST_SESSION_IDS)

    certificate = DeletionCertificate.model_validate(result)
    assert certificate.workflow_type == "person"
    assert certificate.workflow_id == workflow_id
    assert certificate.team_id == TEST_TEAM_ID
    assert certificate.dry_run is False
    assert certificate.distinct_ids == TEST_DISTINCT_IDS
    assert certificate.total_recordings_found == 3
    assert certificate.total_deleted == 3
    assert certificate.total_failed == 0


@pytest.mark.asyncio
async def test_delete_recordings_with_person_workflow_dry_run():
    TEST_DISTINCT_IDS = ["5e0c4450-704f-4c9f-aa55-576a6b5d4d0f"]
    TEST_TEAM_ID: int = 45678
    TEST_SESSION_IDS = ["session-1", "session-2"]

    @activity.defn(name="load-recordings-with-person")
    async def load_recordings_with_person_mocked(input: RecordingsWithPersonInput) -> LoadRecordingsPage:
        assert input.distinct_ids == TEST_DISTINCT_IDS
        assert input.team_id == TEST_TEAM_ID
        return LoadRecordingsPage(session_ids=TEST_SESSION_IDS, next_cursor=None)

    @activity.defn(name="bulk-delete-recordings")
    async def bulk_delete_recordings_mocked(input: BulkDeleteInput) -> BulkDeleteResult:
        assert input.dry_run is True
        return BulkDeleteResult(deleted=[])

    task_queue_name = str(uuid.uuid4())
    workflow_id = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue_name,
            workflows=[DeleteRecordingsWithPersonWorkflow],
            activities=[
                load_recordings_with_person_mocked,
                bulk_delete_recordings_mocked,
            ],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            result = await env.client.execute_workflow(
                DeleteRecordingsWithPersonWorkflow.run,
                RecordingsWithPersonInput(
                    distinct_ids=TEST_DISTINCT_IDS,
                    team_id=TEST_TEAM_ID,
                    config=DeletionConfig(dry_run=True),
                ),
                id=workflow_id,
                task_queue=task_queue_name,
            )

    certificate = DeletionCertificate.model_validate(result)
    assert certificate.workflow_type == "person"
    assert certificate.dry_run is True
    assert certificate.total_recordings_found == 2
    assert certificate.total_deleted == 0


@pytest.mark.asyncio
async def test_delete_recordings_with_no_sessions_found():
    TEST_TEAM_ID: int = 77777

    bulk_delete_called = False

    @activity.defn(name="load-recordings-with-team-id")
    async def load_recordings_with_team_id_mocked(input: RecordingsWithTeamInput) -> LoadRecordingsPage:
        return LoadRecordingsPage(session_ids=[], next_cursor=None)

    @activity.defn(name="bulk-delete-recordings")
    async def bulk_delete_recordings_mocked(input: BulkDeleteInput) -> BulkDeleteResult:
        nonlocal bulk_delete_called
        bulk_delete_called = True
        raise AssertionError("Should not be called when no sessions found")

    task_queue_name = str(uuid.uuid4())
    workflow_id = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue_name,
            workflows=[DeleteRecordingsWithTeamWorkflow],
            activities=[
                load_recordings_with_team_id_mocked,
                bulk_delete_recordings_mocked,
            ],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            result = await env.client.execute_workflow(
                DeleteRecordingsWithTeamWorkflow.run,
                RecordingsWithTeamInput(team_id=TEST_TEAM_ID),
                id=workflow_id,
                task_queue=task_queue_name,
            )

    assert bulk_delete_called is False

    certificate = DeletionCertificate.model_validate(result)
    assert certificate.total_recordings_found == 0
    assert certificate.total_deleted == 0
    assert certificate.total_failed == 0


@pytest.mark.asyncio
async def test_delete_recordings_with_team_workflow():
    TEST_TEAM_ID: int = 99999
    TEST_SESSION_IDS = [
        "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
        "b2c3d4e5-f6g7-8901-bcde-f12345678901",
        "c3d4e5f6-g7h8-9012-cdef-123456789012",
    ]

    deleted_sessions: list[str] = []

    @activity.defn(name="load-recordings-with-team-id")
    async def load_recordings_with_team_id_mocked(input: RecordingsWithTeamInput) -> LoadRecordingsPage:
        assert input.team_id == TEST_TEAM_ID
        return LoadRecordingsPage(session_ids=TEST_SESSION_IDS, next_cursor=None)

    @activity.defn(name="bulk-delete-recordings")
    async def bulk_delete_recordings_mocked(input: BulkDeleteInput) -> BulkDeleteResult:
        assert input.team_id == TEST_TEAM_ID
        deleted_sessions.extend(input.session_ids)
        return BulkDeleteResult(deleted=input.session_ids)

    task_queue_name = str(uuid.uuid4())
    workflow_id = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue_name,
            workflows=[DeleteRecordingsWithTeamWorkflow],
            activities=[
                load_recordings_with_team_id_mocked,
                bulk_delete_recordings_mocked,
            ],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            result = await env.client.execute_workflow(
                DeleteRecordingsWithTeamWorkflow.run,
                RecordingsWithTeamInput(team_id=TEST_TEAM_ID),
                id=workflow_id,
                task_queue=task_queue_name,
            )

    assert sorted(deleted_sessions) == sorted(TEST_SESSION_IDS)

    certificate = DeletionCertificate.model_validate(result)
    assert certificate.workflow_type == "team"
    assert certificate.workflow_id == workflow_id
    assert certificate.team_id == TEST_TEAM_ID
    assert certificate.dry_run is False
    assert certificate.total_deleted == 3


@pytest.mark.asyncio
async def test_delete_recordings_with_team_workflow_dry_run():
    TEST_TEAM_ID: int = 44444
    TEST_SESSION_IDS = ["dry-run-session-1", "dry-run-session-2"]

    @activity.defn(name="load-recordings-with-team-id")
    async def load_recordings_with_team_id_mocked(input: RecordingsWithTeamInput) -> LoadRecordingsPage:
        assert input.team_id == TEST_TEAM_ID
        return LoadRecordingsPage(session_ids=TEST_SESSION_IDS, next_cursor=None)

    @activity.defn(name="bulk-delete-recordings")
    async def bulk_delete_recordings_mocked(input: BulkDeleteInput) -> BulkDeleteResult:
        assert input.dry_run is True
        return BulkDeleteResult(deleted=[])

    task_queue_name = str(uuid.uuid4())
    workflow_id = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue_name,
            workflows=[DeleteRecordingsWithTeamWorkflow],
            activities=[
                load_recordings_with_team_id_mocked,
                bulk_delete_recordings_mocked,
            ],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            result = await env.client.execute_workflow(
                DeleteRecordingsWithTeamWorkflow.run,
                RecordingsWithTeamInput(team_id=TEST_TEAM_ID, config=DeletionConfig(dry_run=True)),
                id=workflow_id,
                task_queue=task_queue_name,
            )

    certificate = DeletionCertificate.model_validate(result)
    assert certificate.workflow_type == "team"
    assert certificate.dry_run is True
    assert certificate.total_recordings_found == 2
    assert certificate.total_deleted == 0


@pytest.mark.asyncio
async def test_delete_recordings_with_query_workflow():
    TEST_QUERY = 'events=[{"id":"$pageview","type":"events"}]&date_from=-7d'
    TEST_TEAM_ID: int = 78901
    TEST_SESSION_IDS = [
        "4a1b2c3d-5e6f-7g8h-9i0j-1k2l3m4n5o6p",
        "5b2c3d4e-6f7g-8h9i-0j1k-2l3m4n5o6p7q",
        "6c3d4e5f-7g8h-9i0j-1k2l-3m4n5o6p7q8r",
    ]

    deleted_sessions: list[str] = []

    @activity.defn(name="load-recordings-with-query")
    async def load_recordings_with_query_mocked(input: RecordingsWithQueryInput) -> LoadRecordingsPage:
        assert input.query == TEST_QUERY
        assert input.team_id == TEST_TEAM_ID
        return LoadRecordingsPage(session_ids=TEST_SESSION_IDS, next_cursor=None)

    @activity.defn(name="bulk-delete-recordings")
    async def bulk_delete_recordings_mocked(input: BulkDeleteInput) -> BulkDeleteResult:
        assert input.team_id == TEST_TEAM_ID
        deleted_sessions.extend(input.session_ids)
        return BulkDeleteResult(deleted=input.session_ids)

    task_queue_name = str(uuid.uuid4())
    workflow_id = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue_name,
            workflows=[DeleteRecordingsWithQueryWorkflow],
            activities=[
                load_recordings_with_query_mocked,
                bulk_delete_recordings_mocked,
            ],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            result = await env.client.execute_workflow(
                DeleteRecordingsWithQueryWorkflow.run,
                RecordingsWithQueryInput(query=TEST_QUERY, team_id=TEST_TEAM_ID),
                id=workflow_id,
                task_queue=task_queue_name,
            )

    assert sorted(deleted_sessions) == sorted(TEST_SESSION_IDS)

    certificate = DeletionCertificate.model_validate(result)
    assert certificate.workflow_type == "query"
    assert certificate.workflow_id == workflow_id
    assert certificate.team_id == TEST_TEAM_ID
    assert certificate.query == TEST_QUERY
    assert certificate.dry_run is False
    assert certificate.total_deleted == 3


@pytest.mark.asyncio
async def test_delete_recordings_with_query_workflow_dry_run():
    TEST_QUERY = 'events=[{"id":"$pageview","type":"events"}]&date_from=-30d'
    TEST_TEAM_ID: int = 11111
    TEST_SESSION_IDS = ["7d4e5f6g-8h9i-0j1k-2l3m-4n5o6p7q8r9s", "8e5f6g7h-9i0j-1k2l-3m4n-5o6p7q8r9s0t"]

    @activity.defn(name="load-recordings-with-query")
    async def load_recordings_with_query_mocked(input: RecordingsWithQueryInput) -> LoadRecordingsPage:
        assert input.query == TEST_QUERY
        assert input.team_id == TEST_TEAM_ID
        return LoadRecordingsPage(session_ids=TEST_SESSION_IDS, next_cursor=None)

    @activity.defn(name="bulk-delete-recordings")
    async def bulk_delete_recordings_mocked(input: BulkDeleteInput) -> BulkDeleteResult:
        assert input.dry_run is True
        return BulkDeleteResult(deleted=[])

    task_queue_name = str(uuid.uuid4())
    workflow_id = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue_name,
            workflows=[DeleteRecordingsWithQueryWorkflow],
            activities=[
                load_recordings_with_query_mocked,
                bulk_delete_recordings_mocked,
            ],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            result = await env.client.execute_workflow(
                DeleteRecordingsWithQueryWorkflow.run,
                RecordingsWithQueryInput(query=TEST_QUERY, team_id=TEST_TEAM_ID, config=DeletionConfig(dry_run=True)),
                id=workflow_id,
                task_queue=task_queue_name,
            )

    certificate = DeletionCertificate.model_validate(result)
    assert certificate.workflow_type == "query"
    assert certificate.query == TEST_QUERY
    assert certificate.dry_run is True
    assert certificate.total_recordings_found == 2
    assert certificate.total_deleted == 0


@pytest.mark.asyncio
async def test_delete_recordings_with_batching():
    """Test that large numbers of sessions are batched correctly and certificate aggregates all results."""
    TEST_TEAM_ID: int = 33333
    TEST_SESSION_IDS = [f"session-{i}" for i in range(250)]

    batch_calls: list[list[str]] = []

    @activity.defn(name="load-recordings-with-team-id")
    async def load_recordings_with_team_id_mocked(input: RecordingsWithTeamInput) -> LoadRecordingsPage:
        return LoadRecordingsPage(session_ids=TEST_SESSION_IDS, next_cursor=None)

    @activity.defn(name="bulk-delete-recordings")
    async def bulk_delete_recordings_mocked(input: BulkDeleteInput) -> BulkDeleteResult:
        batch_calls.append(input.session_ids)
        return BulkDeleteResult(deleted=input.session_ids)

    task_queue_name = str(uuid.uuid4())
    workflow_id = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue_name,
            workflows=[DeleteRecordingsWithTeamWorkflow],
            activities=[
                load_recordings_with_team_id_mocked,
                bulk_delete_recordings_mocked,
            ],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            result = await env.client.execute_workflow(
                DeleteRecordingsWithTeamWorkflow.run,
                RecordingsWithTeamInput(team_id=TEST_TEAM_ID, config=DeletionConfig(batch_size=100)),
                id=workflow_id,
                task_queue=task_queue_name,
            )

    # 250 sessions with batch_size=100 should result in 3 batches
    assert len(batch_calls) == 3
    assert len(batch_calls[0]) == 100
    assert len(batch_calls[1]) == 100
    assert len(batch_calls[2]) == 50

    all_deleted = []
    for batch in batch_calls:
        all_deleted.extend(batch)
    assert sorted(all_deleted) == sorted(TEST_SESSION_IDS)

    certificate = DeletionCertificate.model_validate(result)
    assert certificate.total_recordings_found == 250
    assert certificate.total_deleted == 250


@pytest.mark.asyncio
async def test_delete_recordings_certificate_with_mixed_results():
    """Test that the certificate correctly captures mixed results (deleted and failed)."""
    TEST_TEAM_ID: int = 55555
    TEST_SESSION_IDS = ["session-1", "session-2", "session-3", "session-4"]

    @activity.defn(name="load-recordings-with-team-id")
    async def load_recordings_with_team_id_mocked(input: RecordingsWithTeamInput) -> LoadRecordingsPage:
        return LoadRecordingsPage(session_ids=TEST_SESSION_IDS, next_cursor=None)

    @activity.defn(name="bulk-delete-recordings")
    async def bulk_delete_recordings_mocked(input: BulkDeleteInput) -> BulkDeleteResult:
        return BulkDeleteResult(
            deleted=["session-1", "session-2"],
            failed_count=2,
        )

    task_queue_name = str(uuid.uuid4())
    workflow_id = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue_name,
            workflows=[DeleteRecordingsWithTeamWorkflow],
            activities=[
                load_recordings_with_team_id_mocked,
                bulk_delete_recordings_mocked,
            ],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            result = await env.client.execute_workflow(
                DeleteRecordingsWithTeamWorkflow.run,
                RecordingsWithTeamInput(team_id=TEST_TEAM_ID),
                id=workflow_id,
                task_queue=task_queue_name,
            )

    certificate = DeletionCertificate.model_validate(result)
    assert certificate.workflow_type == "team"
    assert certificate.team_id == TEST_TEAM_ID
    assert certificate.total_recordings_found == 4
    assert certificate.total_deleted == 2
    assert certificate.total_failed == 2


@pytest.mark.asyncio
async def test_delete_recordings_with_pagination():
    """Test that the workflow paginates through multiple pages of session IDs."""
    TEST_TEAM_ID: int = 88888
    PAGE_1 = [f"session-{i}" for i in range(100)]
    PAGE_2 = [f"session-{i}" for i in range(100, 150)]

    deleted_sessions: list[str] = []
    load_call_count = 0

    @activity.defn(name="load-recordings-with-team-id")
    async def load_recordings_with_team_id_mocked(input: RecordingsWithTeamInput) -> LoadRecordingsPage:
        nonlocal load_call_count
        load_call_count += 1
        if input.cursor is None:
            return LoadRecordingsPage(session_ids=PAGE_1, next_cursor=PAGE_1[-1])
        else:
            assert input.cursor == PAGE_1[-1]
            return LoadRecordingsPage(session_ids=PAGE_2, next_cursor=None)

    @activity.defn(name="bulk-delete-recordings")
    async def bulk_delete_recordings_mocked(input: BulkDeleteInput) -> BulkDeleteResult:
        deleted_sessions.extend(input.session_ids)
        return BulkDeleteResult(deleted=input.session_ids)

    task_queue_name = str(uuid.uuid4())
    workflow_id = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue_name,
            workflows=[DeleteRecordingsWithTeamWorkflow],
            activities=[
                load_recordings_with_team_id_mocked,
                bulk_delete_recordings_mocked,
            ],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            result = await env.client.execute_workflow(
                DeleteRecordingsWithTeamWorkflow.run,
                RecordingsWithTeamInput(team_id=TEST_TEAM_ID),
                id=workflow_id,
                task_queue=task_queue_name,
            )

    assert load_call_count == 2
    assert sorted(deleted_sessions) == sorted(PAGE_1 + PAGE_2)

    certificate = DeletionCertificate.model_validate(result)
    assert certificate.total_recordings_found == 150
    assert certificate.total_deleted == 150
    assert certificate.total_failed == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "num_sessions, max_per_second, expected_sleep",
    [
        pytest.param(100, 10, 10.0, id="100_sessions_at_10_per_sec"),
        pytest.param(30, 30, 1.0, id="30_sessions_at_30_per_sec"),
        pytest.param(150, 50, 3.0, id="150_sessions_at_50_per_sec"),
    ],
)
async def test_rate_limiting_sleeps_when_execution_is_fast(num_sessions, max_per_second, expected_sleep):
    """When batch execution is instant (frozen time), sleep = num_sessions / max_per_second."""
    TEST_TEAM_ID = 11111
    session_ids = [f"s-{i}" for i in range(num_sessions)]

    @activity.defn(name="load-recordings-with-team-id")
    async def load_mocked(input: RecordingsWithTeamInput) -> LoadRecordingsPage:
        return LoadRecordingsPage(session_ids=session_ids, next_cursor=None)

    @activity.defn(name="bulk-delete-recordings")
    async def delete_mocked(input: BulkDeleteInput) -> BulkDeleteResult:
        return BulkDeleteResult(deleted=input.session_ids)

    task_queue_name = str(uuid.uuid4())
    mock_sleep = AsyncMock()

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue_name,
            workflows=[DeleteRecordingsWithTeamWorkflow],
            activities=[load_mocked, delete_mocked],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            with patch("posthog.temporal.delete_recordings.workflows.asyncio.sleep", mock_sleep):
                await env.client.execute_workflow(
                    DeleteRecordingsWithTeamWorkflow.run,
                    RecordingsWithTeamInput(
                        team_id=TEST_TEAM_ID,
                        config=DeletionConfig(max_deletions_per_second=max_per_second),
                    ),
                    id=str(uuid.uuid4()),
                    task_queue=task_queue_name,
                )

    mock_sleep.assert_called_once()
    actual_sleep = mock_sleep.call_args[0][0]
    assert actual_sleep == pytest.approx(expected_sleep, abs=0.5)


@pytest.mark.asyncio
async def test_rate_limiting_disabled_when_zero():
    """No sleep when max_deletions_per_second=0."""
    TEST_TEAM_ID = 22222
    session_ids = [f"s-{i}" for i in range(50)]

    @activity.defn(name="load-recordings-with-team-id")
    async def load_mocked(input: RecordingsWithTeamInput) -> LoadRecordingsPage:
        return LoadRecordingsPage(session_ids=session_ids, next_cursor=None)

    @activity.defn(name="bulk-delete-recordings")
    async def delete_mocked(input: BulkDeleteInput) -> BulkDeleteResult:
        return BulkDeleteResult(deleted=input.session_ids)

    task_queue_name = str(uuid.uuid4())
    mock_sleep = AsyncMock()

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue_name,
            workflows=[DeleteRecordingsWithTeamWorkflow],
            activities=[load_mocked, delete_mocked],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            with patch("posthog.temporal.delete_recordings.workflows.asyncio.sleep", mock_sleep):
                await env.client.execute_workflow(
                    DeleteRecordingsWithTeamWorkflow.run,
                    RecordingsWithTeamInput(
                        team_id=TEST_TEAM_ID,
                        config=DeletionConfig(max_deletions_per_second=0),
                    ),
                    id=str(uuid.uuid4()),
                    task_queue=task_queue_name,
                )

    mock_sleep.assert_not_called()


def test_delete_recordings_with_person_workflow_parse_inputs():
    result = DeleteRecordingsWithPersonWorkflow.parse_inputs(
        ['{"distinct_ids": ["id1", "id2"], "team_id": 123, "config": {"batch_size": 50}}']
    )
    assert result.distinct_ids == ["id1", "id2"]
    assert result.team_id == 123
    assert result.config.batch_size == 50


def test_delete_recordings_with_team_workflow_parse_inputs():
    result = DeleteRecordingsWithTeamWorkflow.parse_inputs(
        ['{"team_id": 456, "config": {"dry_run": true, "batch_size": 50}}']
    )
    assert result.team_id == 456
    assert result.config.dry_run is True
    assert result.config.batch_size == 50


def test_delete_recordings_with_query_workflow_parse_inputs():
    result = DeleteRecordingsWithQueryWorkflow.parse_inputs(
        [
            '{"query": "date_from=-7d", "team_id": 789, "config": {"dry_run": false, "batch_size": 75}, "query_limit": 500}'
        ]
    )
    assert result.query == "date_from=-7d"
    assert result.team_id == 789
    assert result.config.dry_run is False
    assert result.config.batch_size == 75
    assert result.query_limit == 500


@pytest.mark.asyncio
async def test_purge_deleted_recording_metadata_workflow():
    from datetime import UTC, datetime

    TEST_GRACE_PERIOD_DAYS = 30

    @activity.defn(name="purge-deleted-metadata")
    async def purge_deleted_metadata_mocked(input: PurgeDeletedMetadataInput) -> PurgeDeletedMetadataResult:
        assert input.grace_period_days == TEST_GRACE_PERIOD_DAYS
        now = datetime.now(UTC)
        return PurgeDeletedMetadataResult(
            started_at=now,
            completed_at=now,
        )

    task_queue_name = str(uuid.uuid4())
    workflow_id = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue_name,
            workflows=[PurgeDeletedRecordingMetadataWorkflow],
            activities=[purge_deleted_metadata_mocked],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            result = await env.client.execute_workflow(
                PurgeDeletedRecordingMetadataWorkflow.run,
                PurgeDeletedMetadataInput(grace_period_days=TEST_GRACE_PERIOD_DAYS),
                id=workflow_id,
                task_queue=task_queue_name,
            )

    purge_result = PurgeDeletedMetadataResult.model_validate(result)
    assert purge_result.started_at is not None
    assert purge_result.completed_at is not None


@pytest.mark.asyncio
async def test_delete_recordings_with_session_ids_workflow():
    TEST_TEAM_ID: int = 66666
    TEST_SESSION_IDS = ["session-a", "session-b", "session-c"]

    deleted_sessions: list[str] = []

    @activity.defn(name="bulk-delete-recordings")
    async def bulk_delete_recordings_mocked(input: BulkDeleteInput) -> BulkDeleteResult:
        assert input.team_id == TEST_TEAM_ID
        deleted_sessions.extend(input.session_ids)
        return BulkDeleteResult(deleted=input.session_ids)

    task_queue_name = str(uuid.uuid4())
    workflow_id = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue_name,
            workflows=[DeleteRecordingsWithSessionIdsWorkflow],
            activities=[bulk_delete_recordings_mocked],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            result = await env.client.execute_workflow(
                DeleteRecordingsWithSessionIdsWorkflow.run,
                RecordingsWithSessionIdsInput(
                    session_ids=TEST_SESSION_IDS,
                    team_id=TEST_TEAM_ID,
                    config=DeletionConfig(reason="test cleanup"),
                ),
                id=workflow_id,
                task_queue=task_queue_name,
            )

    assert sorted(deleted_sessions) == sorted(TEST_SESSION_IDS)

    certificate = DeletionCertificate.model_validate(result)
    assert certificate.workflow_type == "session_ids"
    assert certificate.workflow_id == workflow_id
    assert certificate.team_id == TEST_TEAM_ID
    assert certificate.dry_run is False
    assert certificate.reason == "test cleanup"
    assert certificate.total_recordings_found == 3
    assert certificate.total_deleted == 3
    assert certificate.total_failed == 0


@pytest.mark.asyncio
async def test_delete_recordings_with_session_ids_workflow_chunks_large_input():
    """Session IDs are processed in chunks of 10,000 — verify multiple bulk_delete calls."""
    TEST_TEAM_ID: int = 66666
    TEST_SESSION_IDS = [f"session-{i}" for i in range(25_000)]

    batch_calls: list[list[str]] = []

    @activity.defn(name="bulk-delete-recordings")
    async def bulk_delete_recordings_mocked(input: BulkDeleteInput) -> BulkDeleteResult:
        batch_calls.append(input.session_ids)
        return BulkDeleteResult(deleted=input.session_ids)

    task_queue_name = str(uuid.uuid4())
    workflow_id = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue_name,
            workflows=[DeleteRecordingsWithSessionIdsWorkflow],
            activities=[bulk_delete_recordings_mocked],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            result = await env.client.execute_workflow(
                DeleteRecordingsWithSessionIdsWorkflow.run,
                RecordingsWithSessionIdsInput(
                    session_ids=TEST_SESSION_IDS,
                    team_id=TEST_TEAM_ID,
                    source_filename="big-export.csv",
                ),
                id=workflow_id,
                task_queue=task_queue_name,
            )

    # 25,000 sessions with default batch_size=100 → 3 chunks of 10k, each producing 100 bulk_delete calls
    all_deleted = [sid for batch in batch_calls for sid in batch]
    assert len(all_deleted) == 25_000
    assert sorted(all_deleted) == sorted(TEST_SESSION_IDS)

    certificate = DeletionCertificate.model_validate(result)
    assert certificate.workflow_type == "session_ids"
    assert certificate.source_filename == "big-export.csv"
    assert certificate.total_recordings_found == 25_000
    assert certificate.total_deleted == 25_000
    assert certificate.total_failed == 0


@pytest.mark.asyncio
async def test_delete_recordings_with_session_ids_workflow_dry_run():
    TEST_TEAM_ID: int = 66666
    TEST_SESSION_IDS = ["session-a", "session-b"]

    @activity.defn(name="bulk-delete-recordings")
    async def bulk_delete_recordings_mocked(input: BulkDeleteInput) -> BulkDeleteResult:
        assert input.dry_run is True
        return BulkDeleteResult(deleted=[])

    task_queue_name = str(uuid.uuid4())
    workflow_id = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue_name,
            workflows=[DeleteRecordingsWithSessionIdsWorkflow],
            activities=[bulk_delete_recordings_mocked],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            result = await env.client.execute_workflow(
                DeleteRecordingsWithSessionIdsWorkflow.run,
                RecordingsWithSessionIdsInput(
                    session_ids=TEST_SESSION_IDS, team_id=TEST_TEAM_ID, config=DeletionConfig(dry_run=True)
                ),
                id=workflow_id,
                task_queue=task_queue_name,
            )

    certificate = DeletionCertificate.model_validate(result)
    assert certificate.workflow_type == "session_ids"
    assert certificate.dry_run is True
    assert certificate.total_recordings_found == 2
    assert certificate.total_deleted == 0


def test_delete_recordings_with_session_ids_workflow_parse_inputs():
    result = DeleteRecordingsWithSessionIdsWorkflow.parse_inputs(
        ['{"session_ids": ["s1", "s2"], "team_id": 123, "config": {"batch_size": 50}}']
    )
    assert result.session_ids == ["s1", "s2"]
    assert result.team_id == 123
    assert result.config.batch_size == 50


def test_purge_deleted_recording_metadata_workflow_parse_inputs():
    result = PurgeDeletedRecordingMetadataWorkflow.parse_inputs(['{"grace_period_days": 14}'])
    assert result.grace_period_days == 14


@pytest.mark.parametrize(
    "team_ids, expected_calls",
    [
        pytest.param([1, 2, 3], 3, id="three_teams"),
        pytest.param([42], 1, id="single_team"),
        pytest.param([], 0, id="empty_list"),
    ],
)
def test_queue_delete_team_recordings(team_ids, expected_calls):
    from posthog.tasks.tasks import _queue_delete_team_recordings

    mock_handle = AsyncMock()
    mock_client = AsyncMock()
    mock_client.start_workflow = AsyncMock(return_value=mock_handle)

    async def fake_connect():
        return mock_client

    with patch("posthog.temporal.common.client.async_connect", side_effect=fake_connect):
        _queue_delete_team_recordings(team_ids)

    assert mock_client.start_workflow.call_count == expected_calls
    for call in mock_client.start_workflow.call_args_list:
        assert call.args[0] == "delete-recordings-with-team"
        assert call.args[1].team_id in team_ids


def test_queue_delete_team_recordings_raises_when_temporal_unavailable():
    from posthog.tasks.tasks import _queue_delete_team_recordings

    async def fail_connect():
        raise RuntimeError("Temporal unavailable")

    with patch("posthog.temporal.common.client.async_connect", side_effect=fail_connect):
        with pytest.raises(RuntimeError, match="Temporal unavailable"):
            _queue_delete_team_recordings([1])
