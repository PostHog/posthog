# EE extended functions for SessionRecording model
from datetime import timedelta

import structlog
from django.utils import timezone
from prometheus_client import Histogram, Counter

from posthog import settings
from posthog.session_recordings.models.session_recording import SessionRecording
from posthog.storage import object_storage, session_recording_v2_object_storage
from posthog.storage.session_recording_v2_object_storage import BlockFetchError
from posthog.session_recordings.session_recording_v2_service import list_blocks

logger = structlog.get_logger(__name__)

MINIMUM_AGE_FOR_RECORDING = timedelta(
    minutes=int(settings.get_from_env("SESSION_RECORDING_MINIMUM_AGE_MINUTES", 24 * 60))
)

MAXIMUM_AGE_FOR_RECORDING_V2 = timedelta(
    minutes=int(settings.get_from_env("SESSION_RECORDING_V2_MAXIMUM_AGE_MINUTES", 90 * 24 * 60))
)

# we have 30, 90, and 365-day retention possible
# if we don't act on retention before 90 days has passed, then the recording will be deleted
# so, if 100 days have passed, then there's no point trying to persist a recording
MAXIMUM_AGE_FOR_RECORDING = timedelta(days=int(settings.get_from_env("SESSION_RECORDING_MAXIMUM_AGE_DAYS", 100)))

SNAPSHOT_PERSIST_TIME_HISTOGRAM = Histogram(
    "snapshot_persist_time_seconds",
    "We persist recording snapshots from S3, how long does that take?",
)

SNAPSHOT_PERSIST_SUCCESS_COUNTER = Counter(
    "snapshot_persist_success",
    "Count of session recordings that were successfully persisted",
    labelnames=["team_id"],
)

SNAPSHOT_PERSIST_FAILURE_COUNTER = Counter(
    "snapshot_persist_failure",
    "Count of session recordings that failed to be persisted",
    labelnames=["team_id"],
)

SNAPSHOT_PERSIST_TOO_YOUNG_COUNTER = Counter(
    "snapshot_persist_too_young",
    "Count of session recordings that were too young to be persisted",
)

RECORDING_PERSIST_START_COUNTER = Counter(
    "recording_persist_started",
    "Count of session recordings that were persisted",
)

# V2 specific metrics
SNAPSHOT_PERSIST_TIME_V2_HISTOGRAM = Histogram(
    "snapshot_persist_time_v2_seconds",
    "We persist v2 recording snapshots from S3, how long does that take?",
)

SNAPSHOT_PERSIST_SUCCESS_V2_COUNTER = Counter(
    "snapshot_persist_success_v2",
    "Count of v2 session recordings that were successfully persisted",
)

SNAPSHOT_PERSIST_FAILURE_V2_COUNTER = Counter(
    "snapshot_persist_failure_v2",
    "Count of v2 session recordings that failed to be persisted",
)

SNAPSHOT_PERSIST_TOO_YOUNG_V2_COUNTER = Counter(
    "snapshot_persist_too_young_v2",
    "Count of v2 session recordings that were too young to be persisted",
)

SNAPSHOT_PERSIST_TOO_OLD_V2_COUNTER = Counter(
    "snapshot_persist_too_old_v2",
    "Count of v2 session recordings that were too old to be persisted",
)

RECORDING_PERSIST_START_V2_COUNTER = Counter(
    "recording_persist_started_v2",
    "Count of v2 session recordings that were persisted",
)


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
        # The recording is too recent to be persisted.
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
        SNAPSHOT_PERSIST_SUCCESS_COUNTER.labels(team_id=team_id).inc()
        return
    else:
        SNAPSHOT_PERSIST_FAILURE_COUNTER.labels(team_id=team_id).inc()
        logger.error(
            "No snapshots found to copy in S3 when persisting a recording",
            recording_id=recording_id,
            team_id=team_id,
            target_prefix=target_prefix,
            source_prefix=source_prefix,
        )
        raise InvalidRecordingForPersisting("Could not persist recording: " + recording_id)


def _persist_recording_v2_impl(recording_id: str, team_id: int) -> None:
    """Internal implementation of persist_recording_v2"""
    storage_client = session_recording_v2_object_storage.client()
    if not storage_client.is_enabled() or not storage_client.is_lts_enabled():
        return

    recording = SessionRecording.objects.select_related("team").get(session_id=recording_id, team_id=team_id)

    if not recording:
        raise Exception(f"Recording {recording_id} not found")

    if recording.deleted:
        logger.info(
            "Persisting recording v2: skipping as recording is deleted",
            recording_id=recording_id,
            team_id=team_id,
        )
        return

    RECORDING_PERSIST_START_V2_COUNTER.inc()

    recording.load_metadata()

    now = timezone.now()
    if not recording.start_time:
        SNAPSHOT_PERSIST_TOO_YOUNG_V2_COUNTER.inc()
        recording.save()
        return

    if recording.start_time > now - MINIMUM_AGE_FOR_RECORDING:
        SNAPSHOT_PERSIST_TOO_YOUNG_V2_COUNTER.inc()
        recording.save()
        return

    if recording.start_time < now - MAXIMUM_AGE_FOR_RECORDING_V2:
        SNAPSHOT_PERSIST_TOO_OLD_V2_COUNTER.inc()
        recording.save()
        return

    blocks = list_blocks(recording)
    if not blocks:
        logger.info(
            "No v2 metadata found for recording or recording is incomplete, skipping v2 persistence",
            recording_id=recording_id,
            team_id=team_id,
        )
        SNAPSHOT_PERSIST_FAILURE_V2_COUNTER.inc()
        return

    decompressed_blocks = []
    with SNAPSHOT_PERSIST_TIME_V2_HISTOGRAM.time():
        for block in blocks:
            try:
                decompressed_block = storage_client.fetch_block(block.url)
                decompressed_blocks.append(decompressed_block)
            except BlockFetchError:
                logger.exception(
                    "Failed to fetch block",
                    recording_id=recording_id,
                    team_id=team_id,
                )
                SNAPSHOT_PERSIST_FAILURE_V2_COUNTER.inc()
                return

        full_recording_data = "\n".join(decompressed_blocks)

        target_key, error = storage_client.store_lts_recording(recording_id, full_recording_data)
        if error:
            logger.error(
                error,
                recording_id=recording_id,
                team_id=team_id,
            )
            SNAPSHOT_PERSIST_FAILURE_V2_COUNTER.inc()
            return

        recording.full_recording_v2_path = target_key
        recording.save()
        SNAPSHOT_PERSIST_SUCCESS_V2_COUNTER.inc()


def persist_recording_v2(recording_id: str, team_id: int) -> None:
    """Persist a recording to S3 using the v2 format"""
    try:
        _persist_recording_v2_impl(recording_id, team_id)
    except Exception:
        SNAPSHOT_PERSIST_FAILURE_V2_COUNTER.inc()
        raise
