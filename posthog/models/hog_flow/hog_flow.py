from typing import TYPE_CHECKING, Final

from django.db import models
from django.db.models.signals import post_save
from django.dispatch.dispatcher import receiver

import structlog

from posthog.helpers.encrypted_fields import EncryptedJSONStringField
from posthog.models.action.action import Action
from posthog.models.hog_function_template import HogFunctionTemplate
from posthog.models.team.team import Team
from posthog.models.utils import UUIDTModel
from posthog.plugins.plugin_server_api import reload_hog_flows_on_workers

if TYPE_CHECKING:
    pass

logger = structlog.get_logger(__name__)

# Billable action types that are subject to rate limiting and quota tracking
# These action types incur costs and are counted against customer quotas
BILLABLE_ACTION_TYPES: Final[set[str]] = {
    "function",  # General function/webhook actions
    "function_email",  # Email sending actions
    "function_sms",  # SMS sending actions
    "function_push",  # Push notification actions
}


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
    variables = models.JSONField(default=list, null=True, blank=True)

    # Pre-computed set of billable action types in this workflow for efficient quota checking
    # Contains only billable action types: 'function', 'function_email', 'function_sms', 'function_push'
    billable_action_types = models.JSONField(default=list, null=True, blank=True)

    # Encrypted storage for secret inputs across all function actions, keyed by action ID.
    # encrypted_inputs holds secrets for the live (published) actions.
    # draft_encrypted_inputs holds secrets for draft actions, keeping them isolated from live.
    encrypted_inputs: EncryptedJSONStringField = EncryptedJSONStringField(null=True, blank=True)
    draft_encrypted_inputs: EncryptedJSONStringField = EncryptedJSONStringField(null=True, blank=True)

    # Draft storage for active workflows: stores pending edits separately from live config
    draft = models.JSONField(null=True, blank=True)
    draft_updated_at = models.DateTimeField(null=True, blank=True)

    FUNCTION_ACTION_TYPES: Final = {"function", "function_email", "function_sms", "function_push"}

    @staticmethod
    def extract_secret_inputs(
        actions: list,
        trigger: dict,
        existing_encrypted: dict | None,
    ) -> tuple[list, dict | None]:
        """
        For each function action, separates secret inputs (based on the template's
        inputs_schema) from actions[].config.inputs into a dict keyed by action ID.

        Returns (modified_actions, encrypted_inputs_dict_or_none).
        Does not mutate the existing_encrypted dict.
        """
        if not actions or not isinstance(actions, list):
            return actions, existing_encrypted

        encrypted_inputs = dict(existing_encrypted) if existing_encrypted else {}

        trigger_is_function = (trigger or {}).get("type") in ("webhook", "manual", "tracking_pixel", "schedule")

        for action in actions:
            action_type = action.get("type", "")
            config = action.get("config", {})
            action_id = action.get("id", "")

            is_function_action = action_type in HogFlow.FUNCTION_ACTION_TYPES
            is_function_trigger = action_type == "trigger" and trigger_is_function

            if not (is_function_action or is_function_trigger):
                continue

            template_id = config.get("template_id", "")
            if not template_id:
                continue

            template = HogFunctionTemplate.get_template(template_id)
            if not template or not template.inputs_schema:
                continue

            raw_inputs = config.get("inputs", {}) or {}
            action_encrypted = encrypted_inputs.get(action_id, {}) or {}

            final_inputs = {}
            final_encrypted = {}

            for schema in template.inputs_schema:
                key = schema.get("key", "")
                if not key:
                    continue
                value = raw_inputs.get(key)
                encrypted_value = action_encrypted.get(key)

                # Treat the {"secret": True} marker from the API as "unchanged"
                is_secret_marker = isinstance(value, dict) and value.get("secret") is True and len(value) == 1

                if not schema.get("secret"):
                    if value is not None:
                        final_inputs[key] = value
                else:
                    if value and not is_secret_marker:
                        final_encrypted[key] = value
                    elif encrypted_value:
                        final_encrypted[key] = encrypted_value

            # Keep any non-secret inputs that aren't in the schema (e.g. mappings-derived)
            for key, value in raw_inputs.items():
                if key not in final_inputs and not any(
                    s.get("key") == key and s.get("secret") for s in template.inputs_schema
                ):
                    final_inputs[key] = value

            config["inputs"] = final_inputs
            if final_encrypted:
                encrypted_inputs[action_id] = final_encrypted
            elif action_id in encrypted_inputs:
                del encrypted_inputs[action_id]

        return actions, encrypted_inputs if encrypted_inputs else None

    def save(self, *args, **kwargs):
        self.actions, self.encrypted_inputs = self.extract_secret_inputs(
            self.actions, self.trigger or {}, self.encrypted_inputs
        )
        return super().save(*args, **kwargs)

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
