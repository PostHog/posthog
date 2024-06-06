import json

from django.db import models
from django.db.models.signals import post_save
from django.dispatch.dispatcher import receiver

from posthog.models.action.action import Action
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

    # TODO: Rename to "variables"
    inputs_schema: models.JSONField = models.JSONField(null=True)
    inputs: models.JSONField = models.JSONField(null=True)
    filters: models.JSONField = models.JSONField(null=True, blank=True)

    @property
    def filter_action_ids(self) -> list[int]:
        try:
            return [int(action["id"]) for action in self.filters["actions"]]
        except KeyError:
            return []

    def compile_filters_bytecode(self, actions: dict[int, Action]):
        from .utils import hog_function_filters_to_expr
        from posthog.hogql.bytecode import create_bytecode

        try:
            self.filters["bytecode"] = create_bytecode(hog_function_filters_to_expr(self, actions))
        except Exception:
            # TODO: Capture exception
            self.filters["bytecode"] = None

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

    try:
        affected_hog_functions = (
            HogFunction.objects.prefetch_related("team")
            .filter(team=instance.team_id)
            .filter(filters__contains={"actions": [{"id": str(instance.id)}]})
        )

        all_related_actions = Action.objects.filter(team=instance.team_id).filter(
            id__in=[
                action_id for hog_function in affected_hog_functions for action_id in hog_function.filter_action_ids
            ]
        )

        actions_by_id = {action.id: action for action in all_related_actions}

        for hog_function in affected_hog_functions:
            hog_function.compile_filters_bytecode(actions=actions_by_id)

        updates = HogFunction.objects.bulk_update(affected_hog_functions, ["filters"])
        print("Updated", updates)
    except Exception as e:
        # TODO: How to handle exceptions here?
        pass
