# EE extended functions for SessionRecording model

import json
from datetime import timedelta
from typing import Optional

import structlog
from django.utils import timezone
from prometheus_client import Histogram
from sentry_sdk import capture_exception, capture_message

from posthog import settings
from posthog.event_usage import report_team_action
from posthog.models.session_recording.metadata import PersistedRecordingV1
from posthog.models.session_recording.session_recording import SessionRecording
from posthog.session_recordings.session_recording_helpers import compress_to_string, decompress
from posthog.storage import object_storage

logger = structlog.get_logger(__name__)

SNAPSHOT_PERSIST_TIME_HISTOGRAM = Histogram(
    "snapshot_persist_time_seconds",
    "We persist recording snapshots from S3 or from ClickHouse, how long does that take?",
    labelnames=["source"],
)

MINIMUM_AGE_FOR_RECORDING = timedelta(hours=24)


def persist_recording(recording_id: str, team_id: int) -> None:
    """Persist a recording to the S3"""

    logger.info("Persisting recording: init", recording_id=recording_id, team_id=team_id)

    start_time = timezone.now()

    if not settings.OBJECT_STORAGE_ENABLED:
        return

    recording = SessionRecording.objects.select_related("team").get(session_id=recording_id, team_id=team_id)

    if not recording:
        raise Exception(f"Recording {recording_id} not found")

    if recording.deleted:
        logger.info(
            "Persisting recording: skipping as recording is deleted", recording_id=recording_id, team_id=team_id
        )
        return

    logger.info("Persisting recording: loading metadata...", recording_id=recording_id, team_id=team_id)

    recording.load_metadata()

    if not recording.start_time or timezone.now() < recording.start_time + MINIMUM_AGE_FOR_RECORDING:
        # Recording is too recent to be persisted.
        # We can save the metadata as it is still useful for querying, but we can't move to S3 yet.
        logger.info(
            "Persisting recording: skipping as recording start time is less than MINIMUM_AGE_FOR_RECORDING",
            recording_id=recording_id,
            team_id=team_id,
        )
        recording.save()
        return

    # if snapshots are already in blob storage, then we can just copy the files between buckets
    with SNAPSHOT_PERSIST_TIME_HISTOGRAM.labels(source="S3").time():
        target_prefix = recording.build_object_storage_path("2023-08-01")
        source_prefix = recording.build_blob_ingestion_storage_path()
        copied_count = object_storage.copy_objects(source_prefix, target_prefix)

    if copied_count > 0:
        recording.storage_version = "2023-08-01"
        recording.object_storage_path = target_prefix
        recording.save()
        logger.info("Persisting recording: done!", recording_id=recording_id, team_id=team_id, source="s3")
        return
    else:
        # TODO this can be removed when we're happy with the new storage version
        with SNAPSHOT_PERSIST_TIME_HISTOGRAM.labels(source="ClickHouse").time():
            recording.load_snapshots(100_000)  # TODO: Paginate rather than hardcode a limit

            content: PersistedRecordingV1 = {
                "version": "2022-12-22",
                "distinct_id": recording.distinct_id,
                "snapshot_data_by_window_id": recording.snapshot_data_by_window_id,
            }

            string_content = json.dumps(content, default=str)
            string_content = compress_to_string(string_content)

            logger.info("Persisting recording: writing to S3...", recording_id=recording_id, team_id=team_id)

            try:
                object_path = recording.build_object_storage_path("2022-12-22")
                object_storage.write(object_path, string_content.encode("utf-8"))
                recording.object_storage_path = object_path
                recording.save()

                report_team_action(
                    recording.team,
                    "session recording persisted",
                    {"total_time_ms": (timezone.now() - start_time).total_seconds() * 1000},
                )

                logger.info(
                    "Persisting recording: done!", recording_id=recording_id, team_id=team_id, source="ClickHouse"
                )
            except object_storage.ObjectStorageError as ose:
                capture_exception(ose)
                report_team_action(
                    recording.team,
                    "session recording persist failed",
                    {"total_time_ms": (timezone.now() - start_time).total_seconds() * 1000, "error": str(ose)},
                )
                logger.error(
                    "session_recording.object-storage-error",
                    recording_id=recording.session_id,
                    exception=ose,
                    exc_info=True,
                )


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
            content = object_storage.read(recording.object_storage_path)
            decompressed = json.loads(decompress(content))
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
