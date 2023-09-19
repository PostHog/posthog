from datetime import timedelta

import structlog
from django.utils import timezone

from ee.session_recordings.session_recording_extensions import persist_recording
from posthog.celery import app
from posthog.session_recordings.models.session_recording import SessionRecording

logger = structlog.get_logger(__name__)


@app.task()
def persist_single_recording(id: str, team_id: int) -> None:
    persist_recording(id, team_id)


@app.task()
def persist_finished_recordings() -> None:
    one_day_old = timezone.now() - timedelta(hours=24)
    finished_recordings = SessionRecording.objects.filter(created_at__lte=one_day_old, object_storage_path=None)

    logger.info("Persisting finished recordings", count=finished_recordings.count())

    for recording in finished_recordings:
        persist_single_recording.delay(recording.session_id, recording.team_id)
