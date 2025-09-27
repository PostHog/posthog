from posthog.temporal.delete_recording.activities import delete_recording_blocks, load_recording_blocks
from posthog.temporal.delete_recording.workflow import DeleteRecordingWorkflow

WORKFLOWS = [
    DeleteRecordingWorkflow,
]

ACTIVITIES = [
    load_recording_blocks,
    delete_recording_blocks,
]
