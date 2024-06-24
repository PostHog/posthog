from typing import Optional

from django.db import models
from django.db.models.signals import post_save
from django.dispatch.dispatcher import receiver

from posthog.cdp.templates.hog_function_template import HogFunctionTemplate
from posthog.models.action.action import Action
from posthog.models.team.team import Team
from posthog.models.utils import UUIDModel
from posthog.plugins.plugin_server_api import reload_hog_functions_on_workers


class HogFunction(UUIDModel):
    team: models.ForeignKey = models.ForeignKey("Team", on_delete=models.CASCADE)
    name: models.CharField = models.CharField(max_length=400, null=True, blank=True)
    description: models.TextField = models.TextField(blank=True, default="")
    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True, blank=True)
    created_by: models.ForeignKey = models.ForeignKey("User", on_delete=models.SET_NULL, null=True, blank=True)
    deleted: models.BooleanField = models.BooleanField(default=False)
    updated_at: models.DateTimeField = models.DateTimeField(auto_now=True)
    enabled: models.BooleanField = models.BooleanField(default=False)

    icon_url: models.TextField = models.TextField(null=True, blank=True)
    hog: models.TextField = models.TextField()
    bytecode: models.JSONField = models.JSONField(null=True, blank=True)
    inputs_schema: models.JSONField = models.JSONField(null=True)
    inputs: models.JSONField = models.JSONField(null=True)
    filters: models.JSONField = models.JSONField(null=True, blank=True)
    template_id: models.CharField = models.CharField(max_length=400, null=True, blank=True)

    @property
    def template(self) -> Optional[HogFunctionTemplate]:
        from posthog.cdp.templates import HOG_FUNCTION_TEMPLATES_BY_ID

        return HOG_FUNCTION_TEMPLATES_BY_ID.get(self.template_id, None)

    @property
    def filter_action_ids(self) -> list[int]:
        if not self.filters:
            return []
        try:
            return [int(action["id"]) for action in self.filters.get("actions", [])]
        except KeyError:
            return []

    def save(self, *args, **kwargs):
        from posthog.cdp.filters import compile_filters_bytecode

        self.filters = compile_filters_bytecode(self.filters, self.team)
        return super().save(*args, **kwargs)

    def __str__(self):
        return self.name


@receiver(post_save, sender=HogFunction)
def hog_function_saved(sender, instance: HogFunction, created, **kwargs):
    reload_hog_functions_on_workers(team_id=instance.team_id, hog_function_ids=[str(instance.id)])


@receiver(post_save, sender=Action)
def action_saved(sender, instance: Action, created, **kwargs):
    # Whenever an action is saved we want to load all hog functions using it
    # and trigger a refresh of the filters bytecode

    from posthog.tasks.hog_functions import refresh_affected_hog_functions

    refresh_affected_hog_functions.delay(action_id=instance.id)


@receiver(post_save, sender=Team)
def team_saved(sender, instance: Team, created, **kwargs):
    from posthog.tasks.hog_functions import refresh_affected_hog_functions

    refresh_affected_hog_functions.delay(team_id=instance.id)
