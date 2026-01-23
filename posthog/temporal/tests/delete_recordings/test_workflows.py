import uuid

import pytest

import temporalio.worker
from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from posthog.temporal.delete_recordings.types import (
    BulkDeleteInput,
    BulkDeleteResult,
    DeletionCertificate,
    PurgeDeletedMetadataInput,
    PurgeDeletedMetadataResult,
    RecordingsWithPersonInput,
    RecordingsWithQueryInput,
    RecordingsWithTeamInput,
)
from posthog.temporal.delete_recordings.workflows import (
    DeleteRecordingsWithPersonWorkflow,
    DeleteRecordingsWithQueryWorkflow,
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
    async def load_recordings_with_person_mocked(input: RecordingsWithPersonInput) -> list[str]:
        assert input.distinct_ids == TEST_DISTINCT_IDS
        assert input.team_id == TEST_TEAM_ID
        return TEST_SESSION_IDS

    @activity.defn(name="bulk-delete-recordings")
    async def bulk_delete_recordings_mocked(input: BulkDeleteInput) -> BulkDeleteResult:
        assert input.team_id == TEST_TEAM_ID
        deleted_sessions.extend(input.session_ids)
        return BulkDeleteResult(
            deleted=input.session_ids,
            not_found=[],
            already_deleted=[],
            errors=[],
        )

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

    # Verify the deletion certificate
    certificate = DeletionCertificate.model_validate(result)
    assert certificate.workflow_type == "person"
    assert certificate.workflow_id == workflow_id
    assert certificate.team_id == TEST_TEAM_ID
    assert certificate.dry_run is False
    assert certificate.distinct_ids == TEST_DISTINCT_IDS
    assert certificate.total_recordings_found == 3
    assert certificate.total_deleted == 3
    assert certificate.total_not_found == 0
    assert certificate.total_already_deleted == 0
    assert certificate.total_errors == 0
    assert len(certificate.deleted_recordings) == 3
    assert sorted([r.session_id for r in certificate.deleted_recordings]) == sorted(TEST_SESSION_IDS)


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
    async def load_recordings_with_team_id_mocked(input: RecordingsWithTeamInput) -> list[str]:
        assert input.team_id == TEST_TEAM_ID
        return TEST_SESSION_IDS

    @activity.defn(name="bulk-delete-recordings")
    async def bulk_delete_recordings_mocked(input: BulkDeleteInput) -> BulkDeleteResult:
        assert input.team_id == TEST_TEAM_ID
        deleted_sessions.extend(input.session_ids)
        return BulkDeleteResult(
            deleted=input.session_ids,
            not_found=[],
            already_deleted=[],
            errors=[],
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

    bulk_delete_called = False

    @activity.defn(name="load-recordings-with-team-id")
    async def load_recordings_with_team_id_mocked(input: RecordingsWithTeamInput) -> list[str]:
        assert input.team_id == TEST_TEAM_ID
        assert input.dry_run is True
        return TEST_SESSION_IDS

    @activity.defn(name="bulk-delete-recordings")
    async def bulk_delete_recordings_mocked(input: BulkDeleteInput) -> BulkDeleteResult:
        nonlocal bulk_delete_called
        bulk_delete_called = True
        raise AssertionError("Should not be called in dry run mode")

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
                RecordingsWithTeamInput(team_id=TEST_TEAM_ID, dry_run=True),
                id=workflow_id,
                task_queue=task_queue_name,
            )

    assert bulk_delete_called is False

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
    async def load_recordings_with_query_mocked(input: RecordingsWithQueryInput) -> list[str]:
        assert input.query == TEST_QUERY
        assert input.team_id == TEST_TEAM_ID
        assert input.dry_run is False
        return TEST_SESSION_IDS

    @activity.defn(name="bulk-delete-recordings")
    async def bulk_delete_recordings_mocked(input: BulkDeleteInput) -> BulkDeleteResult:
        assert input.team_id == TEST_TEAM_ID
        deleted_sessions.extend(input.session_ids)
        return BulkDeleteResult(
            deleted=input.session_ids,
            not_found=[],
            already_deleted=[],
            errors=[],
        )

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
                RecordingsWithQueryInput(query=TEST_QUERY, team_id=TEST_TEAM_ID, dry_run=False),
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

    bulk_delete_called = False

    @activity.defn(name="load-recordings-with-query")
    async def load_recordings_with_query_mocked(input: RecordingsWithQueryInput) -> list[str]:
        assert input.query == TEST_QUERY
        assert input.team_id == TEST_TEAM_ID
        assert input.dry_run is True
        return TEST_SESSION_IDS

    @activity.defn(name="bulk-delete-recordings")
    async def bulk_delete_recordings_mocked(input: BulkDeleteInput) -> BulkDeleteResult:
        nonlocal bulk_delete_called
        bulk_delete_called = True
        raise AssertionError("Should not be called in dry run mode")

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
                RecordingsWithQueryInput(query=TEST_QUERY, team_id=TEST_TEAM_ID, dry_run=True),
                id=workflow_id,
                task_queue=task_queue_name,
            )

    assert bulk_delete_called is False

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
    async def load_recordings_with_team_id_mocked(input: RecordingsWithTeamInput) -> list[str]:
        return TEST_SESSION_IDS

    @activity.defn(name="bulk-delete-recordings")
    async def bulk_delete_recordings_mocked(input: BulkDeleteInput) -> BulkDeleteResult:
        batch_calls.append(input.session_ids)
        return BulkDeleteResult(
            deleted=input.session_ids,
            not_found=[],
            already_deleted=[],
            errors=[],
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
                RecordingsWithTeamInput(team_id=TEST_TEAM_ID, batch_size=100),
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

    # Verify certificate aggregates all batch results
    certificate = DeletionCertificate.model_validate(result)
    assert certificate.total_recordings_found == 250
    assert certificate.total_deleted == 250
    assert len(certificate.deleted_recordings) == 250


@pytest.mark.asyncio
async def test_delete_recordings_certificate_with_mixed_results():
    """Test that the certificate correctly captures mixed results (deleted, not found, already deleted, errors)."""
    TEST_TEAM_ID: int = 55555
    TEST_SESSION_IDS = ["session-1", "session-2", "session-3", "session-4"]

    @activity.defn(name="load-recordings-with-team-id")
    async def load_recordings_with_team_id_mocked(input: RecordingsWithTeamInput) -> list[str]:
        return TEST_SESSION_IDS

    @activity.defn(name="bulk-delete-recordings")
    async def bulk_delete_recordings_mocked(input: BulkDeleteInput) -> BulkDeleteResult:
        return BulkDeleteResult(
            deleted=["session-1"],
            not_found=["session-2"],
            already_deleted=["session-3"],
            errors=[{"session_id": "session-4", "error": "Test error"}],
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
    assert certificate.total_deleted == 1
    assert certificate.total_not_found == 1
    assert certificate.total_already_deleted == 1
    assert certificate.total_errors == 1
    assert len(certificate.deleted_recordings) == 1
    assert certificate.deleted_recordings[0].session_id == "session-1"
    assert certificate.not_found_session_ids == ["session-2"]
    assert certificate.already_deleted_session_ids == ["session-3"]
    assert certificate.errors == [{"session_id": "session-4", "error": "Test error"}]


def test_delete_recordings_with_person_workflow_parse_inputs():
    result = DeleteRecordingsWithPersonWorkflow.parse_inputs(
        ['{"distinct_ids": ["id1", "id2"], "team_id": 123, "batch_size": 50}']
    )
    assert result.distinct_ids == ["id1", "id2"]
    assert result.team_id == 123
    assert result.batch_size == 50


def test_delete_recordings_with_team_workflow_parse_inputs():
    result = DeleteRecordingsWithTeamWorkflow.parse_inputs(['{"team_id": 456, "dry_run": true, "batch_size": 200}'])
    assert result.team_id == 456
    assert result.dry_run is True
    assert result.batch_size == 200


def test_delete_recordings_with_query_workflow_parse_inputs():
    result = DeleteRecordingsWithQueryWorkflow.parse_inputs(
        ['{"query": "date_from=-7d", "team_id": 789, "dry_run": false, "batch_size": 150, "query_limit": 500}']
    )
    assert result.query == "date_from=-7d"
    assert result.team_id == 789
    assert result.dry_run is False
    assert result.batch_size == 150
    assert result.query_limit == 500


@pytest.mark.asyncio
async def test_purge_deleted_recording_metadata_workflow():
    """Test that the purge metadata workflow executes the activity and returns the result."""
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
async def test_purge_deleted_recording_metadata_workflow_with_defaults():
    """Test that the purge metadata workflow uses default values for input parameters."""
    from datetime import UTC, datetime

    @activity.defn(name="purge-deleted-metadata")
    async def purge_deleted_metadata_mocked(input: PurgeDeletedMetadataInput) -> PurgeDeletedMetadataResult:
        assert input.grace_period_days == 7  # default
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
                PurgeDeletedMetadataInput(),  # Use defaults
                id=workflow_id,
                task_queue=task_queue_name,
            )

    purge_result = PurgeDeletedMetadataResult.model_validate(result)
    assert purge_result.started_at is not None
    assert purge_result.completed_at is not None


def test_purge_deleted_recording_metadata_workflow_parse_inputs():
    result = PurgeDeletedRecordingMetadataWorkflow.parse_inputs(['{"grace_period_days": 14}'])
    assert result.grace_period_days == 14


def test_purge_deleted_recording_metadata_workflow_parse_inputs_with_defaults():
    result = PurgeDeletedRecordingMetadataWorkflow.parse_inputs(["{}"])
    assert result.grace_period_days == 7
