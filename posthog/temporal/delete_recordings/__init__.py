from posthog.temporal.delete_recordings.activities import (
    cleanup_session_id_chunks,
    delete_recordings,
    load_recordings_with_person,
    load_recordings_with_query,
    load_recordings_with_team_id,
    load_session_id_chunk,
    purge_deleted_metadata,
)
from posthog.temporal.delete_recordings.workflows import (
    DeleteRecordingsWithPersonWorkflow,
    DeleteRecordingsWithQueryWorkflow,
    DeleteRecordingsWithSessionIdsWorkflow,
    DeleteRecordingsWithTeamWorkflow,
    PurgeDeletedRecordingMetadataWorkflow,
)

WORKFLOWS = [
    DeleteRecordingsWithPersonWorkflow,
    DeleteRecordingsWithTeamWorkflow,
    DeleteRecordingsWithQueryWorkflow,
    DeleteRecordingsWithSessionIdsWorkflow,
    PurgeDeletedRecordingMetadataWorkflow,
]

ACTIVITIES = [
    load_recordings_with_person,
    load_recordings_with_query,
    load_recordings_with_team_id,
    load_session_id_chunk,
    cleanup_session_id_chunks,
    delete_recordings,
    purge_deleted_metadata,
]
