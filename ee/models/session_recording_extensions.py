# EE extended functions for SessionRecording model

import json

from sentry_sdk import capture_exception
import structlog
from posthog import settings
from posthog.api.session_recording import SessionRecordingMetadataSerializer
from posthog.models.session_recording.session_recording import SessionRecording
from posthog.queries.session_recordings.session_recording_events import SessionRecordingEvents
from posthog.session_recordings.session_recording_helpers import compress_to_string
from posthog.storage import object_storage

logger = structlog.get_logger(__name__)


def persist_recording(recording_id: str, team_id: int) -> None:
    """Persist a recording to the S3"""

    logger.info("Persisting recording: init", recording_id=recording_id, team_id=team_id)

    if not settings.OBJECT_STORAGE_ENABLED:
        return

    recording = SessionRecording.objects.select_related("team").get(session_id=recording_id, team_id=team_id)

    if not recording:
        raise Exception(f"Recording {recording_id} not found")

    logger.info("Persisting recording: loading metadata...", recording_id=recording_id, team_id=team_id)
    metadata = SessionRecordingEvents(
        team=recording.team,
        session_recording_id=recording.session_id,
    ).get_metadata()

    if not metadata:
        raise Exception(f"Recording {recording_id} metadata not found")

    logger.info("Persisting recording: loading snapshots...", recording_id=recording_id, team_id=team_id)
    snapshots = SessionRecordingEvents(
        team=recording.team,
        session_recording_id=recording.session_id,
        recording_start_time=None,  # TODO Get this from the model
    ).get_snapshots(
        100000, 0
    )  # TODO: Why 100000?

    ser_metadata = SessionRecordingMetadataSerializer(
        data={
            "segments": metadata["segments"],
            "start_and_end_times_by_window_id": metadata["start_and_end_times_by_window_id"],
            "session_id": recording.session_id,
            "viewed": False,
        }
    )
    ser_metadata.is_valid(True)

    content = {
        "version": "2022-12-22",
        "segments": ser_metadata.data["segments"],
        "start_and_end_times_by_window_id": ser_metadata.data["start_and_end_times_by_window_id"],
        "snapshots": snapshots["snapshot_data_by_window_id"],
    }

    # TODO: This is a hack workaround for datetime conversion
    string_content = compress_to_string(json.dumps(content, indent=4, sort_keys=True, default=str))

    logger.info("Persisting recording: writing to S3...", recording_id=recording_id, team_id=team_id)
    try:
        object_path = recording.build_object_storage_path()
        object_storage.write(object_path, string_content.encode("utf-8"))
        recording.object_storage_path = object_path
        recording.save(update_fields=["object_storage_path"])

        logger.info("Persisting recording: done!", recording_id=recording_id, team_id=team_id)
    except object_storage.ObjectStorageError as ose:
        capture_exception(ose)
        logger.error(
            "session_recording.object-storage-error", recording_id=recording.session_id, exception=ose, exc_info=True
        )
