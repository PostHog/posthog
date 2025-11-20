import structlog
from celery import shared_task

from posthog.models.feature_flag.flags_cache import update_flags_cache
from posthog.models.feature_flag.local_evaluation import update_flag_caches
from posthog.models.team import Team
from posthog.tasks.utils import CeleryQueue

logger = structlog.get_logger(__name__)


@shared_task(ignore_result=True, queue=CeleryQueue.DEFAULT.value)
def update_team_flags_cache(team_id: int) -> None:
    try:
        team = Team.objects.get(id=team_id)
    except Team.DoesNotExist:
        logger.exception("Team does not exist", team_id=team_id)
        return

    update_flag_caches(team)


@shared_task(ignore_result=True, queue=CeleryQueue.DEFAULT.value)
def update_team_service_flags_cache(team_id: int) -> None:
    """
    Update the service flags cache for a specific team.

    This task is triggered when feature flags change or when teams are created,
    ensuring the feature-flags service has fresh data in HyperCache.
    """
    try:
        team = Team.objects.get(id=team_id)
    except Team.DoesNotExist:
        logger.exception("Team does not exist for service flags cache update", team_id=team_id)
        return

    update_flags_cache(team)


@shared_task(ignore_result=True, queue=CeleryQueue.DEFAULT.value)
def sync_all_flags_cache() -> None:
    # Meant to ensure we have all flags cache in sync in case something failed

    # Only select the id from the team queryset
    for team_id in Team.objects.values_list("id", flat=True):
        update_team_flags_cache.delay(team_id)
