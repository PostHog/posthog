# EE extended functions for SessionRecording model
import gzip
import json
from datetime import timedelta, datetime
from typing import Optional, cast

import structlog
from django.utils import timezone
from prometheus_client import Histogram, Counter
from sentry_sdk import capture_exception, capture_message

from posthog import settings
from posthog.session_recordings.models.metadata import PersistedRecordingV1
from posthog.session_recordings.models.session_recording import SessionRecording
from posthog.session_recordings.session_recording_helpers import decompress
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

MINIMUM_AGE_FOR_RECORDING = timedelta(hours=24)


# TODO rename this...
def save_recording_with_new_content(recording: SessionRecording, content: str) -> str:
    if not settings.OBJECT_STORAGE_ENABLED:
        return ""

    logger.info(
        "re-saving recording file into 2023-08-01 LTS storage format",
        recording_id=recording.session_id,
        team_id=recording.team_id,
    )

    target_prefix = recording.build_object_storage_path("2023-08-01")

    start = int(cast(datetime, recording.start_time).timestamp() * 1000)
    end = int(cast(datetime, recording.end_time).timestamp() * 1000)
    new_path = f"{target_prefix}/{start}-{end}"

    zipped_content = gzip.compress(content.encode("utf-8"))
    object_storage.write(
        new_path,
        zipped_content,
        extras={"ContentType": "application/json", "ContentEncoding": "gzip"},
    )

    recording.storage_version = "2023-08-01"
    recording.object_storage_path = target_prefix
    recording.save()

    return new_path


class InvalidRecordingForPersisting(Exception):
    pass


def persist_recording(recording_id: str, team_id: int) -> None:
    """Persist a recording to the S3"""

    logger.info("Persisting recording: init", recording_id=recording_id, team_id=team_id)

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

    logger.info(
        "Persisting recording: loading metadata...",
        recording_id=recording_id,
        team_id=team_id,
    )

    recording.load_metadata()

    if not recording.start_time or timezone.now() < recording.start_time + MINIMUM_AGE_FOR_RECORDING:
        # Recording is too recent to be persisted.
        # We can save the metadata as it is still useful for querying, but we can't move to S3 yet.
        logger.info(
            "Persisting recording: skipping as recording start time is less than MINIMUM_AGE_FOR_RECORDING",
            recording_id=recording_id,
            team_id=team_id,
        )
        SNAPSHOT_PERSIST_TOO_YOUNG_COUNTER.inc()
        recording.save()
        return

    target_prefix = recording.build_object_storage_path("2023-08-01")
    source_prefix = recording.build_blob_ingestion_storage_path()
    # if snapshots are already in blob storage, then we can just copy the files between buckets
    with SNAPSHOT_PERSIST_TIME_HISTOGRAM.time():
        copied_count = object_storage.copy_objects(source_prefix, target_prefix)

    if copied_count > 0:
        recording.storage_version = "2023-08-01"
        recording.object_storage_path = target_prefix
        recording.save()
        SNAPSHOT_PERSIST_SUCCESS_COUNTER.inc()
        logger.info(
            "Persisting recording: done!",
            recording_id=recording_id,
            team_id=team_id,
            source="s3",
        )
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


def load_persisted_recording(recording: SessionRecording) -> Optional[PersistedRecordingV1]:
    """Load a persisted recording from S3"""

    logger.info(
        "Persisting recording load: reading from S3...",
        recording_id=recording.session_id,
        storage_version=recording.storage_version,
        path=recording.object_storage_path,
    )

    # originally storage version was written to the stored content
    # some stored content is stored over multiple files, so we can't rely on that
    # future recordings will have the storage version on the model
    # and will not be loaded here
    if not recording.storage_version:
        try:
            content = object_storage.read(str(recording.object_storage_path))
            decompressed = json.loads(decompress(content)) if content else None
            logger.info(
                "Persisting recording load: loaded!",
                recording_id=recording.session_id,
                path=recording.object_storage_path,
            )

            return decompressed
        except object_storage.ObjectStorageError as ose:
            capture_exception(ose)
            logger.error(
                "session_recording.object-storage-load-error",
                recording_id=recording.session_id,
                path=recording.object_storage_path,
                version="2022-12-22",
                exception=ose,
                exc_info=True,
            )

    capture_message(
        "session_recording.load_persisted_recording.unexpected_recording_storage_version",
        extras={
            "recording_id": recording.session_id,
            "storage_version": recording.storage_version,
            "path": recording.object_storage_path,
        },
        tags={
            "team_id": recording.team_id,
        },
    )
    return None
