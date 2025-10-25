# EE extended functions for SessionRecording model
from datetime import timedelta

from django.utils import timezone

import structlog
from prometheus_client import Counter, Histogram

from posthog import settings
from posthog.session_recordings.models.session_recording import SessionRecording
from posthog.session_recordings.session_recording_v2_service import copy_to_lts

logger = structlog.get_logger(__name__)

# in the debug dev environment, we want to persist recordings immediately since we are only interested in few LTS recordings for testing
# in production, we wait for 24 hours, since we don't want to persist recordings that are still being ingested
MINIMUM_AGE_FOR_RECORDING = timedelta(
    minutes=int(
        settings.get_from_env(
            "SESSION_RECORDING_MINIMUM_AGE_MINUTES", 2 if settings.DEBUG and not settings.TEST else 24 * 60
        )
    )
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


def _persist_recording_v2_impl(recording_id: str, team_id: int) -> None:
    """Internal implementation of persist_recording_v2"""
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

    with SNAPSHOT_PERSIST_TIME_V2_HISTOGRAM.time():
        try:
            target_key = copy_to_lts(recording)
            if target_key:
                recording.full_recording_v2_path = target_key
                recording.save()
                SNAPSHOT_PERSIST_SUCCESS_V2_COUNTER.inc()
            else:
                SNAPSHOT_PERSIST_FAILURE_V2_COUNTER.inc()
        except Exception:
            SNAPSHOT_PERSIST_FAILURE_V2_COUNTER.inc()
            raise


def persist_recording_v2(recording_id: str, team_id: int) -> None:
    """Persist a recording to S3 using the v2 format"""
    try:
        _persist_recording_v2_impl(recording_id, team_id)
    except Exception:
        SNAPSHOT_PERSIST_FAILURE_V2_COUNTER.inc()
        raise
