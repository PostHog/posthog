from posthog.temporal.delete_recordings.activities import (
    delete_recording_blocks,
    delete_recording_lts_data,
    group_recording_blocks,
    load_recording_blocks,
    load_recordings_with_person,
    load_recordings_with_query,
    load_recordings_with_team_id,
    perform_recording_metadata_deletion,
    schedule_recording_metadata_deletion,
)
from posthog.temporal.delete_recordings.workflows import (
    DeleteRecordingMetadataWorkflow,
    DeleteRecordingsWithPersonWorkflow,
    DeleteRecordingsWithQueryWorkflow,
    DeleteRecordingsWithTeamWorkflow,
    DeleteRecordingWorkflow,
)

WORKFLOWS = [
    DeleteRecordingWorkflow,
    DeleteRecordingMetadataWorkflow,
    DeleteRecordingsWithPersonWorkflow,
    DeleteRecordingsWithTeamWorkflow,
    DeleteRecordingsWithQueryWorkflow,
]

ACTIVITIES = [
    load_recording_blocks,
    delete_recording_blocks,
    delete_recording_lts_data,
    load_recordings_with_person,
    group_recording_blocks,
    load_recordings_with_query,
    load_recordings_with_team_id,
    perform_recording_metadata_deletion,
    schedule_recording_metadata_deletion,
]
