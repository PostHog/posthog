from typing import Any

import structlog
from celery import shared_task

from ee.session_recordings.ai.embeddings_queries import (
    fetch_errors_by_session_without_embeddings,
    fetch_recordings_without_embeddings,
)
from ee.session_recordings.ai.embeddings_runner import (
    SessionEmbeddingsRunner,
    ErrorEmbeddingsPreparation,
    SessionEventsEmbeddingsPreparation,
)
from ee.session_recordings.ai.error_clustering import error_clustering
from posthog import settings
from posthog.models import Team
from posthog.tasks.utils import CeleryQueue
from django.core.cache import cache

logger = structlog.get_logger(__name__)


# rate limits are per worker, and this task makes multiple calls to open AI
# we currently are allowed 500 calls per minute, so let's rate limit each worker
# to much less than that
@shared_task(ignore_result=False, queue=CeleryQueue.SESSION_REPLAY_EMBEDDINGS.value, rate_limit="75/m")
def embed_batch_of_recordings_task(recordings: list[Any], team_id: int) -> None:
    try:
        team = Team.objects.get(id=team_id)
        runner = SessionEmbeddingsRunner(team=team)

        runner.run(recordings, embeddings_preparation=SessionEventsEmbeddingsPreparation)

        results = fetch_errors_by_session_without_embeddings(team.pk)
        runner.run(results, embeddings_preparation=ErrorEmbeddingsPreparation)
    except Team.DoesNotExist:
        logger.info(f"[embed_batch_of_recordings_task] Team {team} does not exist. Skipping.")
        pass


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

    for team_id in settings.REPLAY_EMBEDDINGS_ALLOWED_TEAMS:
        try:
            recordings = fetch_recordings_without_embeddings(int(team_id))
            logger.info(
                f"[generate_recordings_embeddings_batch] Fetched {len(recordings)} recordings",
                recordings=recordings,
                flow="embeddings",
                team_id=team_id,
            )
            embed_batch_of_recordings_task.si(recordings, int(team_id)).apply_async()
        except Exception as e:
            logger.error(f"[generate_recordings_embeddings_batch] Error: {e}.", exc_info=True, error=e)
            pass


@shared_task(ignore_result=True)
def generate_replay_embedding_error_clusters() -> None:
    for team_id in settings.REPLAY_EMBEDDINGS_ALLOWED_TEAMS:
        try:
            cluster_replay_error_embeddings.si(int(team_id)).apply_async()
        except Exception as e:
            logger.error(f"[generate_replay_error_clusters] Error: {e}.", exc_info=True, error=e)
            pass


@shared_task(ignore_result=True, queue=CeleryQueue.SESSION_REPLAY_EMBEDDINGS.value)
def cluster_replay_error_embeddings(team_id: int) -> None:
    try:
        team = Team.objects.get(id=team_id)
        clusters = error_clustering(team)

        cache.set(f"cluster_errors_{team.pk}", clusters, settings.CACHED_RESULTS_TTL)

        logger.info(
            f"[generate_replay_error_clusters] Completed for team",
            flow="embeddings",
            team_id=team_id,
        )
    except Team.DoesNotExist:
        logger.info(f"[generate_replay_error_clusters] Team {team} does not exist. Skipping.")
        pass
