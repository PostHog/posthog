from dataclasses import asdict, dataclass
from typing import Literal, Optional, Union, get_args

from django.db import models
from django.db.models.signals import post_delete, post_save
from django.dispatch.dispatcher import receiver
from django.utils import timezone

from posthog.hogql.errors import BaseHogQLError
from posthog.models.signals import mutable_receiver
from posthog.plugins.plugin_server_api import drop_action_on_workers, reload_action_on_workers


ActionStepMatching = Literal["contains", "regex", "exact"]
ACTION_STEP_MATCHING_OPTIONS: tuple[ActionStepMatching, ...] = get_args(ActionStepMatching)


@dataclass
class ActionStepJSON:
    tag_name: Optional[str] = None
    text: Optional[str] = None
    text_matching: Optional[ActionStepMatching] = None
    href: Optional[str] = None
    href_matching: Optional[ActionStepMatching] = None
    selector: Optional[str] = None
    url: Optional[str] = None
    url_matching: Optional[ActionStepMatching] = "contains"
    event: Optional[str] = None
    properties: Optional[list[dict]] = None


class Action(models.Model):
    name = models.CharField(max_length=400, null=True, blank=True)
    team = models.ForeignKey("Team", on_delete=models.CASCADE)
    description = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True, blank=True)
    created_by = models.ForeignKey("User", on_delete=models.SET_NULL, null=True, blank=True)
    deleted = models.BooleanField(default=False)
    events = models.ManyToManyField("Event", blank=True)
    post_to_slack = models.BooleanField(default=False)
    slack_message_format = models.CharField(default="", max_length=1200, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    bytecode = models.JSONField(null=True, blank=True)
    bytecode_error = models.TextField(blank=True, null=True)
    steps_json = models.JSONField(null=True, blank=True)
    pinned_at = models.DateTimeField(blank=True, null=True, default=None)

    # DEPRECATED: these were used before ClickHouse was our database
    is_calculating = models.BooleanField(default=False)
    last_calculated_at = models.DateTimeField(default=timezone.now, blank=True)

    class Meta:
        indexes = [models.Index(fields=["team_id", "-updated_at"])]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        self.refresh_bytecode()
        super().save(*args, **kwargs)

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
            "pinned": bool(self.pinned_at),
            "pinned_at": self.pinned_at,
        }

    @property
    def steps(self) -> list[ActionStepJSON]:
        return [ActionStepJSON(**step) for step in self.steps_json or []]

    @steps.setter
    def steps(self, value: list[dict]):
        # TRICKY: This is a little tricky as DRF will deserialize this here as a dict but typing wise we would expect an ActionStepJSON
        self.steps_json = [asdict(ActionStepJSON(**step)) for step in value]

    def get_step_events(self) -> list[Union[str, None]]:
        return [action_step.event for action_step in self.steps]

    def refresh_bytecode(self):
        from posthog.hogql.property import action_to_expr
        from posthog.hogql.bytecode import create_bytecode

        try:
            new_bytecode = create_bytecode(action_to_expr(self)).bytecode
            if new_bytecode != self.bytecode or self.bytecode_error is not None:
                self.bytecode = new_bytecode
                self.bytecode_error = None
        except BaseHogQLError as e:
            # There are several known cases when bytecode generation can fail. Instead of spamming
            # Sentry with errors, ignore those cases for now.
            if self.bytecode is not None or self.bytecode_error != str(e):
                self.bytecode = None
                self.bytecode_error = str(e)


@receiver(post_save, sender=Action)
def action_saved(sender, instance: Action, created, **kwargs):
    reload_action_on_workers(team_id=instance.team_id, action_id=instance.id)


@mutable_receiver(post_delete, sender=Action)
def action_deleted(sender, instance: Action, **kwargs):
    drop_action_on_workers(team_id=instance.team_id, action_id=instance.id)
