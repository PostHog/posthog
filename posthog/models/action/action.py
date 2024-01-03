import json
from typing import List, Any

from django.db import models
from django.db.models import Q
from django.db.models.signals import post_delete, post_save
from django.dispatch.dispatcher import receiver
from django.utils import timezone

from posthog.hogql.errors import HogQLException
from posthog.models.signals import mutable_receiver
from posthog.redis import get_client


class Action(models.Model):
    class Meta:
        indexes = [models.Index(fields=["team_id", "-updated_at"])]

    name: models.CharField = models.CharField(max_length=400, null=True, blank=True)
    team: models.ForeignKey = models.ForeignKey("Team", on_delete=models.CASCADE)
    description: models.TextField = models.TextField(blank=True, default="")
    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True, blank=True)
    created_by: models.ForeignKey = models.ForeignKey("User", on_delete=models.SET_NULL, null=True, blank=True)
    deleted: models.BooleanField = models.BooleanField(default=False)
    events: models.ManyToManyField = models.ManyToManyField("Event", blank=True)
    post_to_slack: models.BooleanField = models.BooleanField(default=False)
    slack_message_format: models.CharField = models.CharField(default="", max_length=600, blank=True)
    updated_at: models.DateTimeField = models.DateTimeField(auto_now=True)
    bytecode: models.JSONField = models.JSONField(null=True, blank=True)
    bytecode_error: models.TextField = models.TextField(blank=True, null=True)

    # DEPRECATED: these were used before ClickHouse was our database
    is_calculating: models.BooleanField = models.BooleanField(default=False)
    last_calculated_at: models.DateTimeField = models.DateTimeField(default=timezone.now, blank=True)

    def __str__(self):
        return self.name

    def get_analytics_metadata(self):
        return {
            "post_to_slack": self.post_to_slack,
            "name_length": len(self.name),
            "custom_slack_message_format": self.slack_message_format != "",
            "event_count_precalc": self.events.count(),  # `precalc` because events are computed async
            "step_count": self.steps.count(),
            "match_text_count": self.steps.exclude(Q(text="") | Q(text__isnull=True)).count(),
            "match_href_count": self.steps.exclude(Q(href="") | Q(href__isnull=True)).count(),
            "match_selector_count": self.steps.exclude(Q(selector="") | Q(selector__isnull=True)).count(),
            "match_url_count": self.steps.exclude(Q(url="") | Q(url__isnull=True)).count(),
            "has_properties": self.steps.exclude(properties=[]).exists(),
            "deleted": self.deleted,
        }

    def get_step_events(self) -> List[str]:
        return [action_step.event for action_step in self.steps.all()]

    def generate_bytecode(self) -> List[Any]:
        from posthog.hogql.property import action_to_expr
        from posthog.hogql.bytecode import create_bytecode

        return create_bytecode(action_to_expr(self))

    def refresh_bytecode(self):
        try:
            new_bytecode = self.generate_bytecode()
            if new_bytecode != self.bytecode or self.bytecode_error is not None:
                self.bytecode = new_bytecode
                self.bytecode_error = None
                self.save(update_fields=["bytecode", "bytecode_error"])
        except HogQLException as e:
            # There are several known cases when bytecode generation can fail. Instead of spamming
            # Sentry with errors, ignore those cases for now.
            if self.bytecode is not None or self.bytecode_error != str(e):
                self.bytecode = None
                self.bytecode_error = str(e)
                self.save(update_fields=["bytecode", "bytecode_error"])


@receiver(post_save, sender=Action)
def action_saved(sender, instance: Action, created, **kwargs):
    get_client().publish(
        "reload-action",
        json.dumps({"teamId": instance.team_id, "actionId": instance.id}),
    )


@mutable_receiver(post_delete, sender=Action)
def action_deleted(sender, instance: Action, **kwargs):
    get_client().publish("drop-action", json.dumps({"teamId": instance.team_id, "actionId": instance.id}))
