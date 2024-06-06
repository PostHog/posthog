from datetime import timedelta

import structlog
from celery import shared_task
from django.utils import timezone
from prometheus_client import Counter

from ee.session_recordings.session_recording_extensions import persist_recording
from posthog.session_recordings.models.session_recording import SessionRecording
from posthog.tasks.utils import CeleryQueue

logger = structlog.get_logger(__name__)

REPLAY_NEEDS_PERSISTENCE_COUNTER = Counter(
    "snapshot_persist_persistence_task_queued",
    "Count of session recordings that need to be persisted",
    # we normally avoid team label but not all teams pin recordings so there shouldn't be _too_ many labels here
    labelnames=["team_id"],
)


@shared_task(
    ignore_result=True,
    queue=CeleryQueue.SESSION_REPLAY_PERSISTENCE.value,
)
def persist_single_recording(id: str, team_id: int) -> None:
    persist_recording(id, team_id)


@shared_task(
    ignore_result=True,
    queue=CeleryQueue.SESSION_REPLAY_PERSISTENCE.value,
)
def persist_finished_recordings() -> None:
    one_day_old = timezone.now() - timedelta(hours=24)
    finished_recordings = SessionRecording.objects.filter(created_at__lte=one_day_old, object_storage_path=None)

    logger.info("Persisting finished recordings", count=finished_recordings.count())

    for recording in finished_recordings:
        REPLAY_NEEDS_PERSISTENCE_COUNTER.labels(team_id=recording.team_id).inc()
        persist_single_recording.delay(recording.session_id, recording.team_id)
