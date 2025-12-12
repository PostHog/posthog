from uuid import UUID, uuid4

from posthog.temporal.export_recording.types import ExportContext, ExportRecordingInput


def test_export_recording_input_creation():
    recording_id = UUID("01938a67-1234-7000-8000-000000000001")
    input = ExportRecordingInput(exported_recording_id=recording_id)
    assert input.exported_recording_id == recording_id


def test_export_context_creation():
    export_id = uuid4()
    recording_id = UUID("01938a67-5678-7000-8000-000000000002")
    context = ExportContext(
        export_id=export_id, exported_recording_id=recording_id, session_id="test-session-id", team_id=67890
    )
    assert context.export_id == export_id
    assert context.exported_recording_id == recording_id
    assert context.session_id == "test-session-id"
    assert context.team_id == 67890


def test_export_context_mutability():
    export_id = uuid4()
    recording_id = UUID("01938a67-9abc-7000-8000-000000000003")
    context = ExportContext(
        export_id=export_id, exported_recording_id=recording_id, session_id="original-id", team_id=123
    )
    context.session_id = "new-id"
    assert context.session_id == "new-id"


def test_export_recording_input_mutability():
    recording_id = UUID("01938a67-def0-7000-8000-000000000004")
    new_recording_id = UUID("01938a67-1111-7000-8000-000000000005")
    input = ExportRecordingInput(exported_recording_id=recording_id)
    input.exported_recording_id = new_recording_id
    assert input.exported_recording_id == new_recording_id
