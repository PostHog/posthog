from uuid import uuid4

from posthog.temporal.import_recording.types import ImportContext, ImportRecordingInput


def test_import_recording_input_creation():
    input = ImportRecordingInput(team_id=123, export_file="/tmp/export.zip")
    assert input.team_id == 123
    assert input.export_file == "/tmp/export.zip"


def test_import_context_creation():
    import_id = uuid4()
    context = ImportContext(
        team_id=123,
        import_id=import_id,
        s3_prefix="team/123/session/abc",
        session_id="abc",
    )
    assert context.team_id == 123
    assert context.import_id == import_id
    assert context.s3_prefix == "team/123/session/abc"
    assert context.session_id == "abc"
