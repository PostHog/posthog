import json

from django.db import models
from django.db.models.signals import post_delete, post_save
from django.dispatch.dispatcher import receiver

from posthog.models.signals import mutable_receiver
from posthog.redis import get_client


class ActionStep(models.Model):
    CONTAINS = "contains"
    REGEX = "regex"
    EXACT = "exact"
    STRING_MATCHING = [(CONTAINS, CONTAINS), (REGEX, REGEX), (EXACT, EXACT)]

    action: models.ForeignKey = models.ForeignKey("Action", related_name="steps", on_delete=models.CASCADE)
    tag_name: models.CharField = models.CharField(max_length=400, null=True, blank=True)
    text: models.CharField = models.CharField(max_length=400, null=True, blank=True)
    text_matching: models.CharField = models.CharField(
        # The implicit default is EXACT - no explicit default to avoid migration woes
        max_length=400,
        choices=STRING_MATCHING,
        null=True,
        blank=True,
    )
    href: models.CharField = models.CharField(max_length=65535, null=True, blank=True)
    href_matching: models.CharField = models.CharField(
        # The implicit default is EXACT - no explicit default to avoid migration woes
        max_length=400,
        choices=STRING_MATCHING,
        null=True,
        blank=True,
    )
    selector: models.CharField = models.CharField(max_length=65535, null=True, blank=True)
    url: models.CharField = models.CharField(max_length=65535, null=True, blank=True)
    url_matching: models.CharField = models.CharField(
        # This is from before text_matching and href_matching, which is why there's an explicit default of CONTAINS
        max_length=400,
        choices=STRING_MATCHING,
        default=CONTAINS,
        null=True,
        blank=True,
    )
    event: models.CharField = models.CharField(max_length=400, null=True, blank=True)
    properties: models.JSONField = models.JSONField(default=list, null=True, blank=True)
    # DEPRECATED, DISUSED
    name: models.CharField = models.CharField(max_length=400, null=True, blank=True)


@receiver(post_save, sender=ActionStep)
def action_step_saved(sender, instance: ActionStep, created, **kwargs):
    instance.action.refresh_bytecode()
    get_client().publish(
        "reload-action",
        json.dumps({"teamId": instance.action.team_id, "actionId": instance.action.id}),
    )


@mutable_receiver(post_delete, sender=ActionStep)
def action_step_deleted(sender, instance: ActionStep, **kwargs):
    instance.action.refresh_bytecode()
    get_client().publish(
        "reload-action",
        json.dumps({"teamId": instance.action.team_id, "actionId": instance.action.id}),
    )
