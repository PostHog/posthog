from datetime import timedelta

import structlog
from celery import shared_task
from django.utils import timezone

from posthog.session_recordings.models.session_recording import SessionRecording

logger = structlog.get_logger(__name__)


@shared_task(ignore_result=True)
def embed_single_recording(id: str, team_id: int) -> None:
    _ = SessionRecording.objects.get(id=id, team_id=team_id)
    # TODO: do the embedding


@shared_task(ignore_result=True)
def generate_recording_embeddings() -> None:
    one_day_old = timezone.now() - timedelta(hours=24)
    one_week_old = timezone.now() - timedelta(days=7)
    finished_recordings = SessionRecording.objects.filter(
        created_at__lte=one_week_old, created_at__gte=one_day_old, object_storage_path=None
    )

    logger.info("Embedding finished recordings", count=finished_recordings.count())

    for recording in finished_recordings:
        embed_single_recording.delay(recording.session_id, recording.team_id)
