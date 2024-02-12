from typing import Any

import structlog
from celery import shared_task, chord

from ee.session_recordings.ai.generate_embeddings import (
    fetch_recordings_without_embeddings,
    generate_recording_embeddings,
)
from posthog import settings
from posthog.tasks.utils import CeleryQueue

logger = structlog.get_logger(__name__)


@shared_task(ignore_result=False, queue=CeleryQueue.SESSION_REPLAY_EMBEDDINGS.value)
def embed_single_recording(session_id: str, team_id: int) -> None:
    generate_recording_embeddings(session_id, team_id)


@shared_task(ignore_result=True)
def generate_recordings_embeddings_batch_on_complete(args: Any, kwargs: Any) -> None:
    logger.info("Embeddings generation batch completed", args=args, kwargs=kwargs)


@shared_task(ignore_result=True)
def generate_recordings_embeddings_batch() -> None:
    # see https://docs.celeryq.dev/en/stable/userguide/canvas.html
    # we have three jobs to do here
    # 1. get a batch of recordings
    # 2. for each recording - ideally in parallel - generate an embedding
    # 3. update CH with the embeddings in one update operation
    # in Celery that's a chain of tasks
    # with step 2 being a group of tasks
    # we don't really want to run them in parallel
    # because we don't want to hit OpenAI rate limits
    # but with a small enough batch size or some throttling that'll be fine
    # we'll also (eventually) want to handle multiple teams
    # but for now we'll do that naively

    for team in settings.REPLAY_EMBEDDINGS_ALLOWED_TEAMS:
        chord(
            embed_single_recording.delay(recording.session_id, recording.team_id)
            for recording in fetch_recordings_without_embeddings(int(team))
        )(generate_recordings_embeddings_batch_on_complete.s())
