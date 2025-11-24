import structlog
from celery import shared_task

from posthog.models.surveys.survey import surveys_hypercache
from posthog.models.team import Team
from posthog.tasks.utils import CeleryQueue

logger = structlog.get_logger(__name__)


@shared_task(ignore_result=True, queue=CeleryQueue.DEFAULT.value)
def update_team_surveys_cache(team_id: int) -> None:
    try:
        team = Team.objects.get(id=team_id)
    except Team.DoesNotExist:
        logger.exception("Team does not exist", team_id=team_id)
        return

    surveys_hypercache.update_cache(team)


@shared_task(ignore_result=True, queue=CeleryQueue.DEFAULT.value)
def sync_all_surveys_cache() -> None:
    # Meant to ensure we have all flags cache in sync in case something failed

    # Only select the id from the team queryset
    for team_id in Team.objects.values_list("id", flat=True):
        update_team_surveys_cache.delay(team_id)
