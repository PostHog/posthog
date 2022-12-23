# EE extended functions for SessionRecording model

import json
from typing import Optional

import structlog
from sentry_sdk import capture_exception

from posthog import settings
from posthog.models.session_recording.metadata import PersistedRecordingV1
from posthog.models.session_recording.session_recording import SessionRecording
from posthog.session_recordings.session_recording_helpers import compress_to_string, decompress
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

    recording.load_metadata()
    recording.load_snapshots(100000)  # TODO: Paginate rather than hardcode a limit

    content: PersistedRecordingV1 = {
        "version": "2022-12-22",
        "distinct_id": recording.distinct_id,
        "snapshot_data_by_window_id": recording.snapshot_data_by_window_id,
        "start_and_end_times_by_window_id": recording.start_and_end_times_by_window_id,
        "segments": recording.segments,
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


def load_persisted_recording(recording: SessionRecording) -> Optional[PersistedRecordingV1]:
    """Load a persisted recording from S3"""

    logger.info(
        "Persisting recording load: reading from S3...",
        recording_id=recording.session_id,
        path=recording.object_storage_path,
    )

    try:
        content = object_storage.read(recording.object_storage_path)
        decompressed = json.loads(decompress(content))
        logger.info(
            "Persisting recording load: loaded!", recording_id=recording.session_id, path=recording.object_storage_path
        )

        return decompressed
    except object_storage.ObjectStorageError as ose:
        capture_exception(ose)
        logger.error(
            "session_recording.object-storage-load-error",
            recording_id=recording.session_id,
            path=recording.object_storage_path,
            exception=ose,
            exc_info=True,
        )

        return None
