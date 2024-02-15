from typing import Any, List

import structlog
from celery import shared_task

from ee.session_recordings.ai.generate_embeddings import (
    fetch_recordings_without_embeddings,
    embed_batch_of_recordings,
)
from posthog import settings
from posthog.models import Team
from posthog.tasks.utils import CeleryQueue

logger = structlog.get_logger(__name__)


@shared_task(ignore_result=False, queue=CeleryQueue.SESSION_REPLAY_EMBEDDINGS.value)
def embed_batch_of_recordings_task(recordings: List[Any], team_id: int) -> None:
    embed_batch_of_recordings(recordings, team_id)


@shared_task(ignore_result=True)
def generate_recordings_embeddings_batch() -> None:
    # see https://docs.celeryq.dev/en/stable/userguide/canvas.html
    # we have three jobs to do here
    # 1. get a batch of recordings
    # 2. for each recording - ideally in parallel - generate an embedding
    # 3. update CH with the embeddings in one update operation
    # in Celery that's a chain of tasks
    # with step 2 being a group of tasks
    # chord(
    #             embed_single_recording.si(recording.session_id, recording.team_id)
    #             for recording in fetch_recordings_without_embeddings(int(team))
    #         )(generate_recordings_embeddings_batch_on_complete.si())
    # but even the docs call out performance impact of synchronising tasks
    #
    # so, for now, we'll do that naively

    for team in settings.REPLAY_EMBEDDINGS_ALLOWED_TEAMS:
        try:
            recordings = fetch_recordings_without_embeddings(int(team))
            embed_batch_of_recordings_task.si(recordings, int(team)).apply_async()
        except Team.DoesNotExist:
            logger.info(f"[generate_recordings_embeddings_batch] Team {team} does not exist. Skipping.")
            pass
        except Exception as e:
            logger.error(f"[generate_recordings_embeddings_batch] Error: {e}.", exc_info=True, error=e)
            pass
