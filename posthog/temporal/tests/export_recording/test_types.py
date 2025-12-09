from pathlib import Path

from posthog.temporal.export_recording.types import ExportContext, ExportData, ExportRecordingInput


def test_export_recording_input_creation():
    input = ExportRecordingInput(exported_asset_id=12345)
    assert input.exported_asset_id == 12345


def test_export_context_creation():
    context = ExportContext(session_id="test-session-id", team_id=67890)
    assert context.session_id == "test-session-id"
    assert context.team_id == 67890


def test_export_data_creation():
    context = ExportContext(session_id="test-session", team_id=111)
    export_data = ExportData(
        export_context=context,
        clickhouse_rows=Path("/tmp/clickhouse_data.json"),
        recording_data=[Path("/tmp/recording1.json"), Path("/tmp/recording2.json")],
    )
    assert export_data.export_context == context
    assert export_data.clickhouse_rows == Path("/tmp/clickhouse_data.json")
    assert len(export_data.recording_data) == 2
    assert export_data.recording_data[0] == Path("/tmp/recording1.json")
    assert export_data.recording_data[1] == Path("/tmp/recording2.json")


def test_export_data_empty_recording_data():
    context = ExportContext(session_id="empty-session", team_id=222)
    export_data = ExportData(
        export_context=context,
        clickhouse_rows=Path("/tmp/data.json"),
        recording_data=[],
    )
    assert export_data.recording_data == []


def test_export_context_mutability():
    context = ExportContext(session_id="original-id", team_id=123)
    context.session_id = "new-id"
    assert context.session_id == "new-id"


def test_export_recording_input_mutability():
    input = ExportRecordingInput(exported_asset_id=100)
    input.exported_asset_id = 200
    assert input.exported_asset_id == 200
