from celery import shared_task

from posthog.tasks.utils import CeleryQueue


@shared_task(ignore_result=True, queue=CeleryQueue.DEFAULT.value)
def update_team_remote_config(team_id: int) -> None:
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
