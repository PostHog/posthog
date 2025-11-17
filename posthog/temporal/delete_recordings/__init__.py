from posthog.temporal.delete_recordings.activities import (
    delete_recording_blocks,
    group_recording_blocks,
    load_recording_blocks,
    load_recordings_with_person,
    load_recordings_with_query,
)
from posthog.temporal.delete_recordings.workflows import (
    DeleteRecordingsWithPersonWorkflow,
    DeleteRecordingsWithQueryWorkflow,
    DeleteRecordingWorkflow,
)

WORKFLOWS = [
    DeleteRecordingWorkflow,
    DeleteRecordingsWithPersonWorkflow,
    DeleteRecordingsWithQueryWorkflow,
]

ACTIVITIES = [
    load_recording_blocks,
    delete_recording_blocks,
    load_recordings_with_person,
    group_recording_blocks,
    load_recordings_with_query,
]
