from typing import Optional
import json
from django.db import models
from rest_hooks.models import AbstractHook
from posthog.tasks.hooks import DeliverHook
from .team import Team


class Hook(AbstractHook):
    # Replacing the default rest_hooks' user field with team, as our data is per team
    user = None
    team = models.ForeignKey(Team, related_name="%(class)ss", on_delete=models.CASCADE)
    resource_id = models.IntegerField(null=True, blank=True)


def find_and_fire_hook(
    event_name: str,
    instance: models.Model,
    user_override: Optional[Team] = None,
    payload_override: Optional[dict] = None,
):
    hooks = Hook.objects.filter(event=event_name, team=user_override)
    if event_name == "action_performed":
        hooks = hooks.filter(models.Q(resource_id=instance.id) | models.Q(resource_id__isnull=True))
    for hook in hooks:
        hook.deliver_hook(instance, payload_override)


def deliver_hook_wrapper(target, payload, instance, hook):
    # instance is None if using custom event, not built-in
    if instance is not None:
        instance_id = instance.id
    else:
        instance_id = None
    # pass ID's not objects because using pickle for objects is a bad thing
    kwargs = dict(target=target, payload=payload, instance_id=instance_id, hook_id=hook.id)
    DeliverHook.apply_async(kwargs=kwargs)
