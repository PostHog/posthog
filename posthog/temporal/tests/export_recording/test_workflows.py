from uuid import UUID

from posthog.temporal.export_recording.workflows import ExportRecordingWorkflow


def test_export_recording_workflow_parse_inputs():
    result = ExportRecordingWorkflow.parse_inputs(['{"exported_recording_id": "01938a67-1234-7000-8000-000000000001"}'])
    assert result.exported_recording_id == UUID("01938a67-1234-7000-8000-000000000001")


def test_export_recording_workflow_parse_inputs_string_uuid():
    result = ExportRecordingWorkflow.parse_inputs(['{"exported_recording_id": "01938a67-5678-7000-8000-000000000002"}'])
    assert result.exported_recording_id == UUID("01938a67-5678-7000-8000-000000000002")
