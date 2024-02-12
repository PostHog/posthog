import structlog
from celery import shared_task

from posthog.tasks.ee.session_recordings.ai.generate_embeddings import (
    fetch_recordings_without_embeddings,
    generate_recording_embedding,
)
from posthog.tasks.utils import CeleryQueue

logger = structlog.get_logger(__name__)


@shared_task(ignore_result=True, queue=CeleryQueue.SESSION_REPLAY_EMBEDDINGS.value)
def embed_single_recording(session_id: str, team_id: int) -> None:
    generate_recording_embedding(session_id, team_id)


@shared_task(ignore_result=True)
def generate_recording_embeddings() -> None:
    recordings = fetch_recordings_without_embeddings()

    for recording in recordings:
        # push each embedding task to a separate queue
        embed_single_recording.delay(recording.session_id, recording.team_id)
