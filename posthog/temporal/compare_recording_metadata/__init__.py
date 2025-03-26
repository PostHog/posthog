from posthog.temporal.compare_recording_metadata.compare_recording_metadata_workflow import (
    CompareRecordingMetadataWorkflow,
    compare_recording_metadata_activity,
)

WORKFLOWS = [CompareRecordingMetadataWorkflow]
ACTIVITIES = [compare_recording_metadata_activity]
