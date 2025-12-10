from uuid import uuid4

from posthog.temporal.export_recording.types import ExportContext, ExportRecordingInput


def test_export_recording_input_creation():
    input = ExportRecordingInput(exported_asset_id=12345)
    assert input.exported_asset_id == 12345


def test_export_context_creation():
    export_id = uuid4()
    context = ExportContext(export_id=export_id, exported_asset_id=456, session_id="test-session-id", team_id=67890)
    assert context.export_id == export_id
    assert context.exported_asset_id == 456
    assert context.session_id == "test-session-id"
    assert context.team_id == 67890


def test_export_context_mutability():
    export_id = uuid4()
    context = ExportContext(export_id=export_id, exported_asset_id=456, session_id="original-id", team_id=123)
    context.session_id = "new-id"
    assert context.session_id == "new-id"


def test_export_recording_input_mutability():
    input = ExportRecordingInput(exported_asset_id=100)
    input.exported_asset_id = 200
    assert input.exported_asset_id == 200
