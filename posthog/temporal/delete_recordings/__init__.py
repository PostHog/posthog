from posthog.temporal.delete_recordings.activities import (
    bulk_delete_recordings,
    load_recordings_with_person,
    load_recordings_with_query,
    load_recordings_with_team_id,
    purge_deleted_metadata,
)
from posthog.temporal.delete_recordings.workflows import (
    DeleteRecordingsWithPersonWorkflow,
    DeleteRecordingsWithQueryWorkflow,
    DeleteRecordingsWithTeamWorkflow,
    PurgeDeletedRecordingMetadataWorkflow,
)

WORKFLOWS = [
    DeleteRecordingsWithPersonWorkflow,
    DeleteRecordingsWithTeamWorkflow,
    DeleteRecordingsWithQueryWorkflow,
    PurgeDeletedRecordingMetadataWorkflow,
]

ACTIVITIES = [
    load_recordings_with_person,
    load_recordings_with_query,
    load_recordings_with_team_id,
    bulk_delete_recordings,
    purge_deleted_metadata,
]
