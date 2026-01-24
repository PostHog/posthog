from datetime import UTC, datetime

from posthog.temporal.delete_recordings.types import (
    BulkDeleteInput,
    BulkDeleteResult,
    DeletedRecordingEntry,
    DeletionCertificate,
    PurgeDeletedMetadataInput,
    PurgeDeletedMetadataResult,
    RecordingsWithPersonInput,
    RecordingsWithQueryInput,
    RecordingsWithTeamInput,
)


def test_recordings_with_person_input_creation():
    input = RecordingsWithPersonInput(distinct_ids=["user-1", "user-2"], team_id=67890, batch_size=50)
    assert input.distinct_ids == ["user-1", "user-2"]
    assert input.team_id == 67890
    assert input.batch_size == 50


def test_recordings_with_person_input_default_batch_size():
    input = RecordingsWithPersonInput(distinct_ids=["user-1"], team_id=111)
    assert input.distinct_ids == ["user-1"]
    assert input.team_id == 111
    assert input.batch_size == 100


def test_recordings_with_team_input_creation():
    input = RecordingsWithTeamInput(team_id=12345, dry_run=True, batch_size=200)
    assert input.team_id == 12345
    assert input.dry_run is True
    assert input.batch_size == 200


def test_recordings_with_team_input_defaults():
    input = RecordingsWithTeamInput(team_id=54321)
    assert input.team_id == 54321
    assert input.dry_run is False
    assert input.batch_size == 100


def test_recordings_with_query_input_creation():
    query_string = 'events=[{"id":"$pageview","type":"events"}]&date_from=-7d'
    input = RecordingsWithQueryInput(query=query_string, team_id=22222, dry_run=True, batch_size=25)
    assert input.query == query_string
    assert input.team_id == 22222
    assert input.dry_run is True
    assert input.batch_size == 25


def test_recordings_with_query_input_defaults():
    query_string = 'events=[{"id":"$pageview","type":"events"}]'
    input = RecordingsWithQueryInput(query=query_string, team_id=33333)
    assert input.query == query_string
    assert input.team_id == 33333
    assert input.dry_run is False
    assert input.batch_size == 100
    assert input.query_limit == 100


def test_recordings_with_query_input_dry_run_false():
    input = RecordingsWithQueryInput(query="test_query", team_id=44444, dry_run=False)
    assert input.dry_run is False


def test_recordings_with_query_input_dry_run_true():
    input = RecordingsWithQueryInput(query="test_query", team_id=55555, dry_run=True)
    assert input.dry_run is True


def test_bulk_delete_input_creation():
    input = BulkDeleteInput(team_id=123, session_ids=["session-1", "session-2", "session-3"])
    assert input.team_id == 123
    assert input.session_ids == ["session-1", "session-2", "session-3"]


def test_bulk_delete_result_creation():
    result = BulkDeleteResult(
        deleted=["session-1", "session-2"],
        not_found=["session-3"],
        already_deleted=["session-4"],
        errors=[{"session_id": "session-5", "error": "Unknown error"}],
    )
    assert result.deleted == ["session-1", "session-2"]
    assert result.not_found == ["session-3"]
    assert result.already_deleted == ["session-4"]
    assert result.errors == [{"session_id": "session-5", "error": "Unknown error"}]


def test_bulk_delete_result_empty():
    result = BulkDeleteResult(
        deleted=[],
        not_found=[],
        already_deleted=[],
        errors=[],
    )
    assert result.deleted == []
    assert result.not_found == []
    assert result.already_deleted == []
    assert result.errors == []


def test_deleted_recording_entry_creation():
    now = datetime.now(UTC)
    entry = DeletedRecordingEntry(session_id="session-123", deleted_at=now)
    assert entry.session_id == "session-123"
    assert entry.deleted_at == now


def test_deletion_certificate_person_workflow():
    started_at = datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC)
    completed_at = datetime(2024, 1, 15, 10, 5, 0, tzinfo=UTC)

    certificate = DeletionCertificate(
        workflow_type="person",
        workflow_id="workflow-abc-123",
        team_id=12345,
        started_at=started_at,
        completed_at=completed_at,
        dry_run=False,
        distinct_ids=["user-1", "user-2"],
        total_recordings_found=5,
        total_deleted=3,
        total_not_found=1,
        total_already_deleted=1,
        total_errors=0,
        deleted_recordings=[
            DeletedRecordingEntry(session_id="session-1", deleted_at=completed_at),
            DeletedRecordingEntry(session_id="session-2", deleted_at=completed_at),
            DeletedRecordingEntry(session_id="session-3", deleted_at=completed_at),
        ],
        not_found_session_ids=["session-4"],
        already_deleted_session_ids=["session-5"],
        errors=[],
    )

    assert certificate.workflow_type == "person"
    assert certificate.workflow_id == "workflow-abc-123"
    assert certificate.team_id == 12345
    assert certificate.distinct_ids == ["user-1", "user-2"]
    assert certificate.query is None
    assert certificate.dry_run is False
    assert certificate.total_deleted == 3
    assert len(certificate.deleted_recordings) == 3


def test_deletion_certificate_query_workflow():
    started_at = datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC)
    completed_at = datetime(2024, 1, 15, 10, 5, 0, tzinfo=UTC)

    certificate = DeletionCertificate(
        workflow_type="query",
        workflow_id="workflow-xyz-456",
        team_id=67890,
        started_at=started_at,
        completed_at=completed_at,
        dry_run=False,
        query="date_from=-7d&events=[...]",
        total_recordings_found=10,
        total_deleted=10,
        total_not_found=0,
        total_already_deleted=0,
        total_errors=0,
        deleted_recordings=[
            DeletedRecordingEntry(session_id=f"session-{i}", deleted_at=completed_at) for i in range(10)
        ],
        not_found_session_ids=[],
        already_deleted_session_ids=[],
        errors=[],
    )

    assert certificate.workflow_type == "query"
    assert certificate.query == "date_from=-7d&events=[...]"
    assert certificate.distinct_ids is None
    assert certificate.total_deleted == 10


def test_deletion_certificate_dry_run():
    started_at = datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC)
    completed_at = datetime(2024, 1, 15, 10, 0, 30, tzinfo=UTC)

    certificate = DeletionCertificate(
        workflow_type="team",
        workflow_id="workflow-dry-run",
        team_id=11111,
        started_at=started_at,
        completed_at=completed_at,
        dry_run=True,
        total_recordings_found=100,
        total_deleted=0,
        total_not_found=0,
        total_already_deleted=0,
        total_errors=0,
        deleted_recordings=[],
        not_found_session_ids=[],
        already_deleted_session_ids=[],
        errors=[],
    )

    assert certificate.dry_run is True
    assert certificate.total_recordings_found == 100
    assert certificate.total_deleted == 0
    assert len(certificate.deleted_recordings) == 0


def test_purge_deleted_metadata_input_creation():
    input = PurgeDeletedMetadataInput(grace_period_days=14)
    assert input.grace_period_days == 14


def test_purge_deleted_metadata_input_defaults():
    input = PurgeDeletedMetadataInput()
    assert input.grace_period_days == 7


def test_purge_deleted_metadata_result_creation():
    started_at = datetime(2024, 1, 15, 3, 0, 0, tzinfo=UTC)
    completed_at = datetime(2024, 1, 15, 3, 15, 0, tzinfo=UTC)

    result = PurgeDeletedMetadataResult(
        started_at=started_at,
        completed_at=completed_at,
    )

    assert result.started_at == started_at
    assert result.completed_at == completed_at


def test_purge_deleted_metadata_result_no_rows():
    started_at = datetime(2024, 1, 15, 3, 0, 0, tzinfo=UTC)
    completed_at = datetime(2024, 1, 15, 3, 0, 5, tzinfo=UTC)

    result = PurgeDeletedMetadataResult(
        started_at=started_at,
        completed_at=completed_at,
    )

    assert result.started_at == started_at
    assert result.completed_at == completed_at
