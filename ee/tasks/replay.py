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

BATCH_SIZE = settings.REPLAY_EMBEDDINGS_BATCH_SIZE


@shared_task(ignore_result=False, queue=CeleryQueue.SESSION_REPLAY_EMBEDDINGS.value, rate_limit="20/m")
def embed_batch_of_recordings_task(recordings: List[Any], team_id: int) -> None:
    embed_batch_of_recordings(recordings, team_id)


@shared_task(ignore_result=True)
def generate_recordings_embeddings_batch() -> None:
    # see https://docs.celeryq.dev/en/stable/userguide/canvas.html
    # we have three jobs to do here
    # 1. get a batch of recordings
    # 2. for each recording - ideally in parallel - generate an embedding
    # 3. update CH with the embeddings in one update operation
    #
    # we have between 6 and 24 workers processing the session embeddings queue
    # with 500 requests per minute allowed that means the rate limit needs to be
    # 500 / 24 = 20.8 per minute
    # we want to process as many recordings as possible - and don't have scaling rules per worker queue
    # workers are set to concurrency of 4 but rate limits are per worker so that shouldn't affect this
    # i.e. we can set 20 per minute and celery won't allow 20 per minute across the concurrency of 4
    # not 20 * 4
    # that means we want to force celery to scale for this queue
    # which means we want to run this task infrequently
    # but generate lots of children tasks
    # so we'll load large pages, and then split them into batches

    for team in settings.REPLAY_EMBEDDINGS_ALLOWED_TEAMS:
        try:
            recordings = fetch_recordings_without_embeddings(int(team))
            logger.info(
                f"[generate_recordings_embeddings_batch] Fetched {len(recordings)} recordings",
                recordings=recordings,
                flow="embeddings",
                team_id=team,
            )
            batches = [recordings[i : i + BATCH_SIZE] for i in range(0, len(recordings), BATCH_SIZE)]
            for batch in batches:
                embed_batch_of_recordings_task.si(batch, int(team)).apply_async()
        except Team.DoesNotExist:
            logger.info(f"[generate_recordings_embeddings_batch] Team {team} does not exist. Skipping.")
            pass
        except Exception as e:
            logger.error(f"[generate_recordings_embeddings_batch] Error: {e}.", exc_info=True, error=e)
            pass
