import structlog
from celery import shared_task

from ee.session_recordings.ai.generate_embeddings import (
    fetch_recordings_without_embeddings,
    generate_recording_embeddings,
)
from posthog.tasks.utils import CeleryQueue

logger = structlog.get_logger(__name__)


@shared_task(ignore_result=True, queue=CeleryQueue.SESSION_REPLAY_EMBEDDINGS.value)
def embed_single_recording(session_id: str, team_id: int) -> None:
    generate_recording_embeddings(session_id, team_id)


@shared_task(ignore_result=True)
def generate_recordings_embeddings_batch() -> None:
    for recording in fetch_recordings_without_embeddings():
        # push each embedding task to a separate queue
        # TODO really we should be doing scatter and gather here
        # so we can do one CH update at the end of a batch
        embed_single_recording.delay(recording.session_id, recording.team_id)
