# EE extended functions for SessionRecording model

import json
from datetime import timedelta
from typing import Optional

import posthoganalytics
import structlog
from django.utils import timezone
from sentry_sdk import capture_exception

from posthog import settings
from posthog.models.session_recording.metadata import PersistedRecordingV1
from posthog.models.session_recording.session_recording import SessionRecording
from posthog.session_recordings.session_recording_helpers import compress_to_string, decompress
from posthog.storage import object_storage

logger = structlog.get_logger(__name__)


MINIMUM_AGE_FOR_RECORDING = timedelta(hours=24)


def capture(recording: SessionRecording, event: str, properties: dict):
    """
    Get the related playlist for a recording and return the distinct_id of the user
    who created it as our best guess at a distinct_id
    """

    playlist_item = recording.playlist_items.select_related("playlist", "playlist__created_by").first()
    if playlist_item:
        posthoganalytics.capture(playlist_item.playlist.created_by.distinct_id, event, properties)


def persist_recording(recording_id: str, team_id: int) -> None:
    """Persist a recording to the S3"""

    logger.info("Persisting recording: init", recording_id=recording_id, team_id=team_id)

    start_time = timezone.now()
    analytics_payload = {
        "total_time_seconds": 0.0,
        "metadata_load_time_seconds": 0.0,
        "snapshots_load_time_seconds": 0.0,
        "content_size_in_bytes": 0,
        "compressed_size_in_bytes": 0,
    }

    if not settings.OBJECT_STORAGE_ENABLED:
        return

    recording = SessionRecording.objects.select_related("team").get(session_id=recording_id, team_id=team_id)

    if not recording:
        raise Exception(f"Recording {recording_id} not found")

    logger.info("Persisting recording: loading metadata...", recording_id=recording_id, team_id=team_id)

    recording.load_metadata()

    analytics_payload["metadata_load_time_seconds"] = (timezone.now() - start_time).total_seconds()

    if not recording.start_time or timezone.now() < recording.start_time + MINIMUM_AGE_FOR_RECORDING:
        # Recording is too recent to be persisted. We can save the metadata as it is still useful for querying but we can't move to S3 yet.
        logger.info(
            "Persisting recording: skipping as recording start time is less than MINIMUM_AGE_FOR_RECORDING",
            recording_id=recording_id,
            team_id=team_id,
        )
        recording.save()
        return

    recording.load_snapshots(100_000)  # TODO: Paginate rather than hardcode a limit
    analytics_payload["snapshots_load_time_seconds"] = (
        timezone.now() - start_time
    ).total_seconds() - analytics_payload["metadata_load_time_seconds"]

    content: PersistedRecordingV1 = {
        "version": "2022-12-22",
        "distinct_id": recording.distinct_id,
        "snapshot_data_by_window_id": recording.snapshot_data_by_window_id,
        "start_and_end_times_by_window_id": recording.start_and_end_times_by_window_id,
        "segments": recording.segments,
    }

    # TODO: This is a hack workaround for datetime conversion
    string_content = json.dumps(content, default=str)
    analytics_payload["content_size_in_bytes"] = len(string_content.encode("utf-8"))
    string_content = compress_to_string(string_content)
    analytics_payload["compressed_size_in_bytes"] = len(string_content.encode("utf-8"))

    logger.info("Persisting recording: writing to S3...", recording_id=recording_id, team_id=team_id)

    try:
        object_path = recording.build_object_storage_path()
        object_storage.write(object_path, string_content.encode("utf-8"))
        recording.object_storage_path = object_path
        recording.save()

        analytics_payload["total_time_seconds"] = (timezone.now() - start_time).total_seconds()
        capture(recording, "session recording persisted", analytics_payload)

        logger.info("Persisting recording: done!", recording_id=recording_id, team_id=team_id)
    except object_storage.ObjectStorageError as ose:
        capture_exception(ose)
        capture(recording, "session recording persist failed", analytics_payload)
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
