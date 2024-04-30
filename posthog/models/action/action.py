from dataclasses import dataclass
import enum
import json
from typing import Any, Literal

from django.db import models
from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch.dispatcher import receiver
from django.utils import timezone

from posthog.hogql.errors import BaseHogQLError
from posthog.models.signals import mutable_receiver
from posthog.redis import get_client


ActionStepMatching = Literal["contains", "regex", "exact"]


@dataclass
class ActionStepJSON:
    tag_name: str
    text: str
    text_matching: ActionStepMatching  # STRING MATCHING
    href: str
    href_matching: ActionStepMatching  # STRING MATCHING
    selector: str
    url: str
    url_matching: ActionStepMatching  # STRING MATCHING, default CONTAINS
    event: str
    properties: list[dict]


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
    steps_json: models.JSONField = models.JSONField(null=True, blank=True)

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
            "step_count": len(self.steps),
            "match_text_count": sum(1 if step.text else 0 for step in self.steps),
            "match_href_count": sum(1 if step.href else 0 for step in self.steps),
            "match_selector_count": sum(1 if step.selector else 0 for step in self.steps),
            "match_url_count": sum(1 if step.url else 0 for step in self.steps),
            "has_properties": any(step.properties for step in self.steps),
            "deleted": self.deleted,
        }

    @property
    def steps(self) -> list[ActionStepJSON]:
        if self.steps_json is None:
            # TODO: This probably doesn't work...
            db_steps = self.action_steps.all()
            return [
                ActionStepJSON(
                    tag_name=step.tag_name,
                    text=step.text,
                    text_matching=ActionStepMaching(step.text_matching),
                    href=step.href,
                    href_matching=ActionStepMaching(step.href_matching),
                    selector=step.selector,
                    url=step.url,
                    url_matching=ActionStepMaching(step.url_matching),
                    event=step.event,
                    properties=step.properties,
                )
                for step in db_steps
            ]

        return [ActionStepJSON(**step) for step in self.steps_json]

    def get_step_events(self) -> list[str]:
        return [action_step.event for action_step in self.steps]

    def generate_bytecode(self) -> list[Any]:
        from posthog.hogql.property import action_to_expr
        from posthog.hogql.bytecode import create_bytecode

        return create_bytecode(action_to_expr(self))

    def refresh_bytecode(self):
        try:
            new_bytecode = self.generate_bytecode()
            if new_bytecode != self.bytecode or self.bytecode_error is not None:
                self.bytecode = new_bytecode
                self.bytecode_error = None
        except BaseHogQLError as e:
            # There are several known cases when bytecode generation can fail. Instead of spamming
            # Sentry with errors, ignore those cases for now.
            if self.bytecode is not None or self.bytecode_error != str(e):
                self.bytecode = None
                self.bytecode_error = str(e)


@receiver(pre_save, sender=Action)
def action_presave(sender, instance: Action, created, **kwargs):
    instance.refresh_bytecode()


@receiver(post_save, sender=Action)
def action_saved(sender, instance: Action, created, **kwargs):
    get_client().publish(
        "reload-action",
        json.dumps({"teamId": instance.team_id, "actionId": instance.id}),
    )


@mutable_receiver(post_delete, sender=Action)
def action_deleted(sender, instance: Action, **kwargs):
    get_client().publish("drop-action", json.dumps({"teamId": instance.team_id, "actionId": instance.id}))
