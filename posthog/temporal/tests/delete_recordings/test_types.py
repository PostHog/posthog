from posthog.temporal.delete_recordings.types import (
    DeleteRecordingMetadataInput,
    Recording,
    RecordingsWithPersonInput,
    RecordingsWithQueryInput,
)


def test_recording_creation():
    recording = Recording(session_id="test-session-id", team_id=12345)
    assert recording.session_id == "test-session-id"
    assert recording.team_id == 12345


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


def test_recordings_with_query_input_dry_run_false():
    input = RecordingsWithQueryInput(query="test_query", team_id=44444, dry_run=False)
    assert input.dry_run is False


def test_recordings_with_query_input_dry_run_true():
    input = RecordingsWithQueryInput(query="test_query", team_id=55555, dry_run=True)
    assert input.dry_run is True


def test_recording_mutability():
    """Test that Recording is mutable."""
    recording = Recording(session_id="test-id", team_id=123)
    recording.session_id = "new-id"
    assert recording.session_id == "new-id"


def test_recordings_with_query_input_mutability():
    """Test that RecordingsWithQueryInput is mutable."""
    input = RecordingsWithQueryInput(query="test", team_id=123)
    input.dry_run = True
    assert input.dry_run is True


def test_delete_recording_metadata_input_defaults():
    input = DeleteRecordingMetadataInput()
    assert input.dry_run is False


def test_delete_recording_metadata_input_dry_run_true():
    input = DeleteRecordingMetadataInput(dry_run=True)
    assert input.dry_run is True


def test_delete_recording_metadata_input_dry_run_false():
    input = DeleteRecordingMetadataInput(dry_run=False)
    assert input.dry_run is False
