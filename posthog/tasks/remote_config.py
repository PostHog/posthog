from celery import shared_task
from django.db.models.signals import post_save
from django.dispatch.dispatcher import receiver
import structlog

from posthog.models.feature_flag.feature_flag import FeatureFlag
from posthog.models.hog_functions.hog_function import HogFunction
from posthog.models.plugin import PluginConfig
from posthog.models.remote_config import RemoteConfig
from posthog.tasks.utils import CeleryQueue
from posthog.models.team import Team

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


@receiver(post_save, sender=Team)
def team_saved(sender, instance: "Team", created, **kwargs):
    update_team_remote_config.delay(instance.id)


@receiver(post_save, sender=FeatureFlag)
def feature_flag_saved(sender, instance: "FeatureFlag", created, **kwargs):
    update_team_remote_config.delay(instance.team.id)


@receiver(post_save, sender=PluginConfig)
def site_app_saved(sender, instance: "PluginConfig", created, **kwargs):
    if (
        instance.team
        and instance.enabled
        and instance.plugin.pluginsourcefile.filename == "site.ts"
        and instance.plugin.pluginsourcefile.status == PluginSourceFile.Status.TRANSPILED
    ):
        update_team_remote_config.delay(instance.team.id)


@receiver(post_save, sender=HogFunction)
def site_function_saved(sender, instance: "HogFunction", created, **kwargs):
    if instance.enabled and instance.type in ("site_destination", "site_app") and instance.transpiled:
        update_team_remote_config.delay(instance.team.id)
