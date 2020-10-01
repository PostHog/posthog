import json
from typing import Optional

from django.db import models
from rest_hooks.models import AbstractHook

from ee.tasks.hooks import DeliverHook
from posthog.models import Team
from posthog.models.utils import generate_random_token


class Hook(AbstractHook):
    id = models.CharField(primary_key=True, max_length=50, default=generate_random_token)
    user = models.ForeignKey("posthog.User", related_name="rest_hooks", on_delete=models.CASCADE)
    team = models.ForeignKey(Team, related_name="rest_hooks", on_delete=models.CASCADE)
    resource_id = models.IntegerField(null=True, blank=True)


def find_and_fire_hook(
    event_name: str,
    instance: models.Model,
    user_override: Optional[Team] = None,
    payload_override: Optional[dict] = None,
):
    hooks = Hook.objects.select_related("user").filter(event=event_name, team=user_override)
    if event_name == "action_performed":
        # action_performed is a resource_id-filterable hook
        hooks = hooks.filter(models.Q(resource_id=instance.pk) | models.Q(resource_id__isnull=True))
    for hook in hooks:
        if hook.user.is_feature_available("zapier"):
            hook.deliver_hook(instance, payload_override)


def deliver_hook_wrapper(target, payload, instance, hook):
    # pass IDs not objects because using pickle for objects is a bad thing
    DeliverHook.apply_async(kwargs=dict(target=target, payload=payload, hook_id=hook.id))
