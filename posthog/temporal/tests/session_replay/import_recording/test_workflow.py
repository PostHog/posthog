from posthog.temporal.session_replay.import_recording.workflow import ImportRecordingWorkflow


def test_import_recording_workflow_parse_inputs():
    input = ImportRecordingWorkflow.parse_inputs(['{"team_id": 123, "export_file": "/tmp/export.zip"}'])
    assert input.team_id == 123
    assert input.export_file == "/tmp/export.zip"
