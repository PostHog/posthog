import json
from typing import Optional

from django.db import models
from django.db.models.signals import post_delete, post_save
from django.dispatch.dispatcher import receiver
from rest_hooks.models import AbstractHook
from statshog.defaults.django import statsd

from ee.tasks.hooks import DeliverHook
from posthog.constants import AvailableFeature
from posthog.models.signals import mutable_receiver
from posthog.models.team import Team
from posthog.models.utils import generate_random_token
from posthog.redis import get_client


class Hook(AbstractHook):
    id = models.CharField(primary_key=True, max_length=50, default=generate_random_token)
    user = models.ForeignKey("posthog.User", related_name="rest_hooks", on_delete=models.CASCADE)
    team = models.ForeignKey("posthog.Team", related_name="rest_hooks", on_delete=models.CASCADE)
    resource_id = models.IntegerField(null=True, blank=True)


def find_and_fire_hook(
    event_name: str, instance: models.Model, user_override: Team, payload_override: Optional[dict] = None,
):
    if not user_override.organization.is_feature_available(AvailableFeature.ZAPIER):
        return
    hooks = Hook.objects.filter(event=event_name, team=user_override)
    if event_name == "action_performed":
        # action_performed is a resource_id-filterable hook
        hooks = hooks.filter(models.Q(resource_id=instance.pk))
    for hook in hooks:
        statsd.incr("posthog_cloud_hooks_rest_fired")
        hook.deliver_hook(instance, payload_override)


def deliver_hook_wrapper(target, payload, instance, hook):
    # pass IDs not objects because using pickle for objects is a bad thing
    DeliverHook.apply_async(kwargs=dict(target=target, payload=payload, hook_id=hook.id))


@receiver(post_save, sender=Hook)
def hook_saved(sender, instance: Hook, created, **kwargs):
    if instance.event == "action_performed":
        get_client().publish(
            "reload-action", json.dumps({"teamId": instance.team_id, "actionId": instance.resource_id})
        )


@mutable_receiver(post_delete, sender=Hook)
def hook_deleted(sender, instance: Hook, **kwargs):
    if instance.event == "action_performed":
        get_client().publish("drop-action", json.dumps({"teamId": instance.team_id, "actionId": instance.resource_id}))
