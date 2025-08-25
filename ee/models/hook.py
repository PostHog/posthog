import json

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.signals import post_delete, post_save
from django.dispatch.dispatcher import receiver

from posthog.models.signals import mutable_receiver
from posthog.models.utils import generate_random_token
from posthog.redis import get_client

HOOK_EVENTS = ["action_performed"]


class Hook(models.Model):
    id = models.CharField(primary_key=True, max_length=50, default=generate_random_token)
    user = models.ForeignKey("posthog.User", related_name="rest_hooks", on_delete=models.CASCADE)
    team = models.ForeignKey("posthog.Team", related_name="rest_hooks", on_delete=models.CASCADE)
    event = models.CharField("Event", max_length=64, db_index=True)
    resource_id = models.IntegerField(null=True, blank=True)
    target = models.URLField("Target URL", max_length=255)
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    def clean(self):
        """Validation for events."""
        if self.event not in HOOK_EVENTS:
            raise ValidationError("Invalid hook event {evt}.".format(evt=self.event))


@receiver(post_save, sender=Hook)
def hook_saved(sender, instance: Hook, created, **kwargs):
    if instance.event == "action_performed":
        get_client().publish(
            "reload-action",
            json.dumps({"teamId": instance.team_id, "actionId": instance.resource_id}),
        )


@mutable_receiver(post_delete, sender=Hook)
def hook_deleted(sender, instance: Hook, **kwargs):
    if instance.event == "action_performed":
        get_client().publish(
            "drop-action",
            json.dumps({"teamId": instance.team_id, "actionId": instance.resource_id}),
        )
