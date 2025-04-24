from .compare_recording_metadata_workflow import (
    CompareRecordingMetadataWorkflow,
    compare_recording_metadata_activity,
)
from .compare_recording_events_workflow import (
    CompareRecordingSnapshotsWorkflow,
    compare_recording_snapshots_activity,
)
from .compare_recording_console_logs_workflow import (
    CompareRecordingConsoleLogsWorkflow,
    compare_recording_console_logs_activity,
)
from .compare_sampled_recording_events_workflow import (
    CompareSampledRecordingEventsWorkflow,
    compare_sampled_recording_events_activity,
)

WORKFLOWS = [
    CompareRecordingMetadataWorkflow,
    CompareRecordingSnapshotsWorkflow,
    CompareRecordingConsoleLogsWorkflow,
    CompareSampledRecordingEventsWorkflow,
]
ACTIVITIES = [
    compare_recording_metadata_activity,
    compare_recording_snapshots_activity,
    compare_recording_console_logs_activity,
    compare_sampled_recording_events_activity,
]
