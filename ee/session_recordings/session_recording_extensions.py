# EE extended functions for SessionRecording model
from datetime import timedelta

import structlog
from django.utils import timezone
from prometheus_client import Histogram, Counter
import snappy

from posthog import settings
from posthog.session_recordings.models.session_recording import SessionRecording
from posthog.storage import object_storage, session_recording_v2_object_storage
from posthog.session_recordings.queries.session_replay_events_v2_test import SessionReplayEventsV2Test

logger = structlog.get_logger(__name__)

MINIMUM_AGE_FOR_RECORDING = timedelta(
    minutes=int(settings.get_from_env("SESSION_RECORDING_MINIMUM_AGE_MINUTES", 24 * 60))
)

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


def persist_recording_v2(recording_id: str, team_id: int) -> None:
    """Persist a recording to S3 using the v2 format"""

    storage_client = session_recording_v2_object_storage.client()
    if not storage_client.is_enabled():
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

    if not recording.start_time or timezone.now() < recording.start_time + MINIMUM_AGE_FOR_RECORDING:
        # Recording is too recent to be persisted.
        # We can save the metadata as it is still useful for querying, but we can't move to S3 yet.
        SNAPSHOT_PERSIST_TOO_YOUNG_V2_COUNTER.inc()
        recording.save()
        return

    # Load metadata from v2 table
    metadata = SessionReplayEventsV2Test().get_metadata(recording_id, recording.team)
    if not metadata:
        logger.info(
            "No v2 metadata found for recording, skipping v2 persistence",
            recording_id=recording_id,
            team_id=team_id,
        )
        SNAPSHOT_PERSIST_FAILURE_V2_COUNTER.inc()
        return

    # Sort blocks by first timestamp
    blocks = sorted(
        zip(
            metadata["block_first_timestamps"],
            metadata["block_last_timestamps"],
            metadata["block_urls"],
        ),
        key=lambda x: x[0],
    )

    # If we started recording halfway through the session, we should not persist
    # as we don't have the complete recording from the start
    if not blocks or blocks[0][0] != metadata["start_time"]:
        logger.info(
            "Recording started halfway through the session or has no blocks, skipping v2 persistence",
            recording_id=recording_id,
            team_id=team_id,
            first_block_timestamp=blocks[0][0] if blocks else None,
            start_time=metadata["start_time"] if metadata else None,
        )
        SNAPSHOT_PERSIST_FAILURE_V2_COUNTER.inc()
        return

    decompressed_blocks = []
    with SNAPSHOT_PERSIST_TIME_V2_HISTOGRAM.time():
        for _, _, block_url in blocks:
            if not block_url:
                logger.error(
                    "Missing block URL in v2 metadata",
                    recording_id=recording_id,
                    team_id=team_id,
                )
                SNAPSHOT_PERSIST_FAILURE_V2_COUNTER.inc()
                return

            decompressed_block, error = storage_client.fetch_block(block_url)
            if error:
                logger.error(
                    error,
                    recording_id=recording_id,
                    team_id=team_id,
                )
                SNAPSHOT_PERSIST_FAILURE_V2_COUNTER.inc()
                return

            decompressed_blocks.append(decompressed_block)

        # Concatenate all blocks
        full_recording_data = "".join(decompressed_blocks)

        # Compress and store the full recording
        try:
            compressed_data = snappy.compress(full_recording_data.encode("utf-8"))
            target_key = f"{settings.SESSION_RECORDING_V2_S3_LTS_PREFIX}/{recording_id}"
            storage_client.write(target_key, compressed_data)
            recording.full_recording_v2_path = target_key
            recording.save()
            logger.info(
                "Successfully persisted v2 recording",
                recording_id=recording_id,
                team_id=team_id,
                block_count=len(decompressed_blocks),
                uncompressed_size=len(full_recording_data),
                compressed_size=len(compressed_data),
            )
            SNAPSHOT_PERSIST_SUCCESS_V2_COUNTER.inc()
        except Exception:
            logger.exception(
                "Failed to persist v2 recording",
                recording_id=recording_id,
                team_id=team_id,
            )
            SNAPSHOT_PERSIST_FAILURE_V2_COUNTER.inc()
            return
