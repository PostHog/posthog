import json

from django.db import models
from django.db.models.signals import post_save
from django.dispatch.dispatcher import receiver

from posthog.models.action.action import Action
from posthog.models.team.team import Team
from posthog.models.utils import UUIDModel
from posthog.redis import get_client


class HogFunction(UUIDModel):
    team: models.ForeignKey = models.ForeignKey("Team", on_delete=models.CASCADE)
    name: models.CharField = models.CharField(max_length=400, null=True, blank=True)
    description: models.TextField = models.TextField(blank=True, default="")
    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True, blank=True)
    created_by: models.ForeignKey = models.ForeignKey("User", on_delete=models.SET_NULL, null=True, blank=True)
    deleted: models.BooleanField = models.BooleanField(default=False)
    updated_at: models.DateTimeField = models.DateTimeField(auto_now=True)
    enabled: models.BooleanField = models.BooleanField(default=False)

    hog: models.TextField = models.TextField()
    bytecode: models.JSONField = models.JSONField(null=True, blank=True)
    inputs_schema: models.JSONField = models.JSONField(null=True)
    inputs: models.JSONField = models.JSONField(null=True)
    filters: models.JSONField = models.JSONField(null=True, blank=True)

    def save(self, *args, **kwargs):
        from posthog.models.cdp.filters import compile_filters_bytecode

        self.filters = compile_filters_bytecode(self.team, self.filters)
        return super().save(*args, **kwargs)

    def __str__(self):
        return self.name


@receiver(post_save, sender=HogFunction)
def hog_function_saved(sender, instance: HogFunction, created, **kwargs):
    get_client().publish(
        "reload-hog-function",
        json.dumps({"teamId": instance.team_id, "hogFunctionId": str(instance.id)}),
    )


@receiver(post_save, sender=Action)
def action_saved(sender, instance: Action, created, **kwargs):
    # Whenever an action is saved we want to load all hog functions using it
    # and trigger a refresh of the filters bytecode

    affected_hog_functions = (
        HogFunction.objects.select_related("team")
        .filter(team_id=instance.team_id)
        .filter(filters__contains={"actions": [{"id": str(instance.id)}]})
    )

    refresh_hog_functions(team_id=instance.team_id, affected_hog_functions=list(affected_hog_functions))


@receiver(post_save, sender=Team)
def team_saved(sender, instance: Team, created, **kwargs):
    affected_hog_functions = (
        HogFunction.objects.select_related("team")
        .filter(team_id=instance.id)
        .filter(filters__contains={"filter_test_accounts": True})
    )

    refresh_hog_functions(team_id=instance.id, affected_hog_functions=list(affected_hog_functions))


def refresh_hog_functions(team_id: int, affected_hog_functions: list[HogFunction]) -> int:
    from posthog.models.cdp.filters import compile_filters_bytecode, get_action_ids_in_filters

    # Optimisation: Fetch all actions for all hog functions at once
    all_related_actions = (
        Action.objects.select_related("team")
        .filter(team_id=team_id)
        .filter(
            id__in=[
                action_id
                for hog_function in affected_hog_functions
                for action_id in get_action_ids_in_filters(hog_function.filters)
            ]
        )
    )

    actions_by_id = {action.id: action for action in all_related_actions}

    for hog_function in affected_hog_functions:
        hog_function.filters = compile_filters_bytecode(hog_function.team, hog_function.filters, actions_by_id)

    updates = HogFunction.objects.bulk_update(affected_hog_functions, ["filters"])

    # TODO Publish update to cdp-processor

    return updates
