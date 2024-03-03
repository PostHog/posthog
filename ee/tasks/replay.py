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


@shared_task(ignore_result=False, queue=CeleryQueue.SESSION_REPLAY_EMBEDDINGS.value, rate_limit="6/m")
def embed_batch_of_recordings_task(recordings: List[Any], team_id: int) -> None:
    embed_batch_of_recordings(recordings, team_id)


@shared_task(ignore_result=True)
def generate_recordings_embeddings_batch() -> None:
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
