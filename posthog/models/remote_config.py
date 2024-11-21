from django.db import models
from django.db.models.signals import post_save
from django.dispatch.dispatcher import receiver
import structlog

from posthog.models.utils import UUIDModel

DEFAULT_STATE = {"state": 0, "tokens": 0, "rating": 0}

logger = structlog.get_logger(__name__)


class RemoteConfig(UUIDModel):
    """
    RemoteConfig is a helper model. There is one per team and stores a highly cacheable JSON object
    as well as JS code for the frontend. It's main function is to react to changes that would affect it,
    update the JSON/JS configs and then sync to the optimized CDN endpoints (such as S3) as well as redis for our legacy
    /decide fallback
    """

    team = models.ForeignKey("Team", on_delete=models.CASCADE)
    config = models.TextField()

    # def save(self, *args, **kwargs):
    #     from posthog.cdp.filters import compile_filters_bytecode

    #     self.move_secret_inputs()
    #     if self.type in TYPES_WITH_COMPILED_FILTERS:
    #         self.filters = compile_filters_bytecode(self.filters, self.team)

    #     return super().save(*args, **kwargs)

    def __str__(self):
        return f"RemoteConfig {self.team_id}"


@receiver(post_save, sender=RemoteConfig)
def remote_config_saved(sender, instance: RemoteConfig, created, **kwargs):
    print("what")
    # Cache the new value somewhere and write to S3
    # reload_hog_functions_on_workers(team_id=instance.team_id, hog_function_ids=[str(instance.id)])


# @receiver(post_save, sender=Action)
# def action_saved(sender, instance: Action, created, **kwargs):
#     # Whenever an action is saved we want to load all hog functions using it
#     # and trigger a refresh of the filters bytecode

#     from posthog.tasks.hog_functions import refresh_affected_hog_functions

#     refresh_affected_hog_functions.delay(action_id=instance.id)


# @receiver(post_save, sender=Team)
# def team_saved(sender, instance: Team, created, **kwargs):
#     from posthog.tasks.hog_functions import refresh_affected_hog_functions

#     refresh_affected_hog_functions.delay(team_id=instance.id)
