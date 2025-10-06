import structlog
from celery import shared_task

from posthog.models.remote_config import RemoteConfig
from posthog.models.team import Team
from posthog.tasks.utils import CeleryQueue

logger = structlog.get_logger(__name__)


@shared_task(ignore_result=True, queue=CeleryQueue.DEFAULT.value)
def update_team_remote_config(team_id: int) -> None:
    try:
        team = Team.objects.get(id=team_id)
    except Team.DoesNotExist:
        logger.exception("Team does not exist", team_id=team_id)
        return

    try:
        remote_config = RemoteConfig.objects.get(team=team)
    except RemoteConfig.DoesNotExist:
        remote_config = RemoteConfig(team=team)

    remote_config.sync()


@shared_task(ignore_result=True, queue=CeleryQueue.DEFAULT.value)
def sync_all_remote_configs() -> None:
    # Meant to ensure we have all configs in sync in case something failed

    # Only select the id from the team queryset
    for team_id in Team.objects.values_list("id", flat=True):
        update_team_remote_config.delay(team_id)
