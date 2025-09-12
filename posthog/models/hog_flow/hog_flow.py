from typing import TYPE_CHECKING

from django.db import models
from django.db.models.signals import post_save
from django.dispatch.dispatcher import receiver

import structlog

from posthog.models.action.action import Action
from posthog.models.team.team import Team
from posthog.models.utils import UUIDTModel
from posthog.plugins.plugin_server_api import reload_hog_flows_on_workers

if TYPE_CHECKING:
    pass

logger = structlog.get_logger(__name__)


class HogFlow(UUIDTModel):
    """
    Stores the version, layout and other meta information for each HogFlow
    """

    class Meta:
        indexes = [
            models.Index(fields=["status", "team"]),
            models.Index(fields=["version", "team"]),
        ]

        constraints = [
            models.UniqueConstraint(fields=["team", "version", "id"], name="unique_version_per_flow"),
        ]

    class State(models.TextChoices):
        DRAFT = "draft"
        ACTIVE = "active"
        ARCHIVED = "archived"

    class ExitCondition(models.TextChoices):
        CONVERSION = "exit_on_conversion"
        TRIGGER_NOT_MATCHED = "exit_on_trigger_not_matched"
        TRIGGER_NOT_MATCHED_OR_CONVERSION = "exit_on_trigger_not_matched_or_conversion"
        ONLY_AT_END = "exit_only_at_end"

    name = models.CharField(max_length=400, null=True, blank=True)
    description = models.TextField(blank=True, default="")
    version = models.IntegerField(default=1)
    team = models.ForeignKey("Team", on_delete=models.CASCADE)
    status = models.CharField(max_length=20, choices=State.choices, default=State.DRAFT)

    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey("User", on_delete=models.SET_NULL, null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    trigger = models.JSONField(default=dict)
    trigger_masking = models.JSONField(null=True, blank=True)
    conversion = models.JSONField(null=True, blank=True)
    exit_condition = models.CharField(max_length=100, choices=ExitCondition.choices, default=ExitCondition.CONVERSION)

    edges = models.JSONField(default=dict)
    actions = models.JSONField(default=dict)
    abort_action = models.CharField(max_length=400, null=True, blank=True)

    def __str__(self):
        return f"HogFlow {self.id}/{self.version}: {self.name}"


@receiver(post_save, sender=HogFlow)
def hog_flow_saved(sender, instance: HogFlow, created, **kwargs):
    reload_hog_flows_on_workers(team_id=instance.team_id, hog_flow_ids=[str(instance.id)])


@receiver(post_save, sender=Action)
def action_saved_for_hog_flows(sender, instance: Action, created, **kwargs):
    # Whenever an action is saved we want to load all hog flows using it
    # and trigger a refresh
    from posthog.tasks.hog_flows import refresh_affected_hog_flows

    refresh_affected_hog_flows.delay(action_id=instance.id)


@receiver(post_save, sender=Team)
def team_saved_for_hog_flows(sender, instance: Team, created, **kwargs):
    from posthog.tasks.hog_flows import refresh_affected_hog_flows

    refresh_affected_hog_flows.delay(team_id=instance.id)
