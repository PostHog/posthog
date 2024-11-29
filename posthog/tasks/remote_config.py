from celery import shared_task
import structlog

from posthog.models.remote_config import RemoteConfig
from posthog.tasks.utils import CeleryQueue
from posthog.models.team import Team

logger = structlog.get_logger(__name__)


@shared_task(ignore_result=True, queue=CeleryQueue.DEFAULT.value)
def update_team_remote_config(team_id: int) -> None:
    team = Team.objects.get(id=team_id)

    try:
        remote_config = RemoteConfig.objects.get(team=team)
    except RemoteConfig.DoesNotExist:
        remote_config = RemoteConfig(team=team)

    remote_config.sync()
