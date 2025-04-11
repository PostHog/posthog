from .compare_recording_metadata_workflow import (
    CompareRecordingMetadataWorkflow,
    compare_recording_metadata_activity,
)
from .compare_recording_events_workflow import (
    CompareRecordingSnapshotsWorkflow,
    compare_recording_snapshots_activity,
)

WORKFLOWS = [CompareRecordingMetadataWorkflow, CompareRecordingSnapshotsWorkflow]
ACTIVITIES = [compare_recording_metadata_activity, compare_recording_snapshots_activity]
