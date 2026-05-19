from posthog.temporal.session_replay.import_recording.activities import (
    build_import_context,
    cleanup_import_data,
    import_event_clickhouse_rows,
    import_recording_data,
    import_replay_clickhouse_rows,
)
from posthog.temporal.session_replay.import_recording.workflow import ImportRecordingWorkflow

IMPORT_RECORDING_WORKFLOWS = [ImportRecordingWorkflow]

IMPORT_RECORDING_ACTIVITIES = [
    build_import_context,
    cleanup_import_data,
    import_event_clickhouse_rows,
    import_recording_data,
    import_replay_clickhouse_rows,
]
