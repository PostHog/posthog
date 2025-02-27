# EE extended functions for SessionRecording model
from datetime import timedelta

import structlog
from django.utils import timezone
from prometheus_client import Histogram, Counter

from posthog import settings
from posthog.session_recordings.models.session_recording import SessionRecording
from posthog.storage import object_storage

logger = structlog.get_logger(__name__)

SNAPSHOT_PERSIST_TIME_HISTOGRAM = Histogram(
    "snapshot_persist_time_seconds",
    "We persist recording snapshots from S3, how long does that take?",
)

SNAPSHOT_PERSIST_SUCCESS_COUNTER = Counter(
    "snapshot_persist_success",
    "Count of session recordings that were successfully persisted",
)

SNAPSHOT_PERSIST_FAILURE_COUNTER = Counter(
    "snapshot_persist_failure",
    "Count of session recordings that failed to be persisted",
)

SNAPSHOT_PERSIST_TOO_YOUNG_COUNTER = Counter(
    "snapshot_persist_too_young",
    "Count of session recordings that were too young to be persisted",
)

RECORDING_PERSIST_START_COUNTER = Counter(
    "recording_persist_started",
    "Count of session recordings that were persisted",
)

MINIMUM_AGE_FOR_RECORDING = timedelta(hours=24)


class InvalidRecordingForPersisting(Exception):
    pass


def persist_recording(recording_id: str, team_id: int) -> None:
    """Persist a recording to the S3"""

    if not settings.OBJECT_STORAGE_ENABLED:
        return

    recording = SessionRecording.objects.select_related("team").get(session_id=recording_id, team_id=team_id)

    if not recording:
        raise Exception(f"Recording {recording_id} not found")

    if recording.deleted:
        logger.info(
            "Persisting recording: skipping as recording is deleted",
            recording_id=recording_id,
            team_id=team_id,
        )
        return

    RECORDING_PERSIST_START_COUNTER.inc()

    recording.load_metadata()

    if not recording.start_time or timezone.now() < recording.start_time + MINIMUM_AGE_FOR_RECORDING:
        # Recording is too recent to be persisted.
        # We can save the metadata as it is still useful for querying, but we can't move to S3 yet.
        SNAPSHOT_PERSIST_TOO_YOUNG_COUNTER.inc()
        recording.save()
        return

    target_prefix = recording.build_blob_lts_storage_path("2023-08-01")
    source_prefix = recording.build_blob_ingestion_storage_path()
    # if snapshots are already in blob storage, then we can just copy the files between buckets
    with SNAPSHOT_PERSIST_TIME_HISTOGRAM.time():
        copied_count = object_storage.copy_objects(source_prefix, target_prefix)

    if copied_count > 0:
        recording.storage_version = "2023-08-01"
        recording.object_storage_path = target_prefix
        recording.save()
        SNAPSHOT_PERSIST_SUCCESS_COUNTER.inc()
        return
    else:
        SNAPSHOT_PERSIST_FAILURE_COUNTER.inc()
        logger.error(
            "No snapshots found to copy in S3 when persisting a recording",
            recording_id=recording_id,
            team_id=team_id,
            target_prefix=target_prefix,
            source_prefix=source_prefix,
        )
        raise InvalidRecordingForPersisting("Could not persist recording: " + recording_id)
