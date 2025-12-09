from posthog.temporal.export_recording.workflows import ExportRecordingWorkflow


def test_export_recording_workflow_parse_input():
    result = ExportRecordingWorkflow.parse_input(['{"exported_asset_id": 12345}'])
    assert result.exported_asset_id == 12345


def test_export_recording_workflow_parse_input_string_id():
    result = ExportRecordingWorkflow.parse_input(['{"exported_asset_id": "67890"}'])
    assert result.exported_asset_id == 67890
