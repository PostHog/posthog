from datetime import UTC, datetime

from posthog.temporal.delete_recordings.types import (
    BulkDeleteInput,
    BulkDeleteResult,
    DeleteFailure,
    DeleteSuccess,
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
    input = RecordingsWithTeamInput(team_id=12345, dry_run=True, batch_size=50)
    assert input.team_id == 12345
    assert input.dry_run is True
    assert input.batch_size == 50


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


def test_bulk_delete_input_creation():
    input = BulkDeleteInput(team_id=123, session_ids=["session-1", "session-2", "session-3"])
    assert input.team_id == 123
    assert input.session_ids == ["session-1", "session-2", "session-3"]


def test_bulk_delete_result_creation():
    result = BulkDeleteResult(
        deleted=["session-1", "session-2"],
        failed=[DeleteFailure(session_id="session-3", error="Unknown error")],
    )
    assert result.deleted == ["session-1", "session-2"]
    assert result.failed == [DeleteFailure(session_id="session-3", error="Unknown error")]


def test_deleted_recording_entry_creation():
    now = datetime.now(UTC)
    entry = DeleteSuccess(session_id="session-123", deleted_at=now)
    assert entry.session_id == "session-123"
    assert entry.deleted_at == now


def test_purge_deleted_metadata_input_creation():
    input = PurgeDeletedMetadataInput(grace_period_days=14)
    assert input.grace_period_days == 14


def test_purge_deleted_metadata_input_defaults():
    input = PurgeDeletedMetadataInput()
    assert input.grace_period_days == 10


def test_purge_deleted_metadata_result_creation():
    started_at = datetime(2024, 1, 15, 3, 0, 0, tzinfo=UTC)
    completed_at = datetime(2024, 1, 15, 3, 15, 0, tzinfo=UTC)

    result = PurgeDeletedMetadataResult(
        started_at=started_at,
        completed_at=completed_at,
    )

    assert result.started_at == started_at
    assert result.completed_at == completed_at
