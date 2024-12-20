import enum
from typing import Optional

from django.db import models
from django.db.models.signals import post_save, post_delete
from django.dispatch.dispatcher import receiver
import structlog

from posthog.cdp.templates.hog_function_template import HogFunctionTemplate
from posthog.helpers.encrypted_fields import EncryptedJSONStringField
from posthog.models.action.action import Action
from posthog.models.plugin import sync_team_inject_web_apps
from posthog.models.signals import mutable_receiver
from posthog.models.team.team import Team
from posthog.models.utils import UUIDModel
from posthog.plugins.plugin_server_api import (
    get_hog_function_status,
    patch_hog_function_status,
    reload_hog_functions_on_workers,
)
from posthog.utils import absolute_uri

DEFAULT_STATE = {"state": 0, "tokens": 0, "rating": 0}

logger = structlog.get_logger(__name__)


class HogFunctionState(enum.Enum):
    UNKNOWN = 0
    HEALTHY = 1
    DEGRADED = 2
    DISABLED_TEMPORARILY = 3
    DISABLED_PERMANENTLY = 4


class HogFunctionType(models.TextChoices):
    DESTINATION = "destination"
    SITE_DESTINATION = "site_destination"
    SITE_APP = "site_app"
    TRANSFORMATION = "transformation"
    EMAIL = "email"
    SMS = "sms"
    PUSH = "push"
    ACTIVITY = "activity"
    ALERT = "alert"
    BROADCAST = "broadcast"


TYPES_THAT_RELOAD_PLUGIN_SERVER = (HogFunctionType.DESTINATION, HogFunctionType.EMAIL, HogFunctionType.TRANSFORMATION)
TYPES_WITH_COMPILED_FILTERS = (HogFunctionType.DESTINATION,)
TYPES_WITH_TRANSPILED_FILTERS = (HogFunctionType.SITE_DESTINATION, HogFunctionType.SITE_APP)
TYPES_WITH_JAVASCRIPT_SOURCE = (HogFunctionType.SITE_DESTINATION, HogFunctionType.SITE_APP)


class HogFunction(UUIDModel):
    class Meta:
        indexes = [
            models.Index(fields=["type", "enabled", "team"]),
        ]

    team = models.ForeignKey("Team", on_delete=models.CASCADE)
    name = models.CharField(max_length=400, null=True, blank=True)
    description = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True, blank=True)
    created_by = models.ForeignKey("User", on_delete=models.SET_NULL, null=True, blank=True)
    deleted = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)
    enabled = models.BooleanField(default=False)
    type = models.CharField(max_length=24, null=True, blank=True)

    icon_url = models.TextField(null=True, blank=True)

    # Hog source, except for the "site_*" types, when it contains TypeScript Source
    hog = models.TextField()
    # Used when the source language is Hog (everything except the "site_*" types)
    bytecode = models.JSONField(null=True, blank=True)
    # Transpiled JavasScript. Used with the "site_*" types
    transpiled = models.TextField(null=True, blank=True)

    inputs_schema = models.JSONField(null=True)
    inputs = models.JSONField(null=True)
    encrypted_inputs: EncryptedJSONStringField = EncryptedJSONStringField(null=True, blank=True)

    filters = models.JSONField(null=True, blank=True)
    mappings = models.JSONField(null=True, blank=True)
    masking = models.JSONField(null=True, blank=True)
    template_id = models.CharField(max_length=400, null=True, blank=True)

    @property
    def template(self) -> Optional[HogFunctionTemplate]:
        from posthog.cdp.templates import HOG_FUNCTION_TEMPLATES_BY_ID

        return HOG_FUNCTION_TEMPLATES_BY_ID.get(self.template_id, None)

    @property
    def filter_action_ids(self) -> list[int]:
        if not self.filters:
            return []
        try:
            return [int(action["id"]) for action in self.filters.get("actions", [])]
        except KeyError:
            return []

    _status: Optional[dict] = None

    @property
    def status(self) -> dict:
        if not self.enabled:
            return DEFAULT_STATE

        if self._status:
            return self._status

        try:
            status = DEFAULT_STATE
            res = get_hog_function_status(self.team_id, self.id)
            if res.status_code == 200:
                status = res.json()
        except Exception as e:
            logger.exception("Failed to fetch function status", error=str(e))

        self._status = status

        return status

    def set_function_status(self, state: int) -> dict:
        if not self.enabled:
            return self.status
        try:
            res = patch_hog_function_status(self.team_id, self.id, state)
            if res.status_code == 200:
                self._status = res.json()
        except Exception as e:
            logger.exception("Failed to set function status", error=str(e))

        return self.status

    def move_secret_inputs(self):
        # Moves any secret inputs to the encrypted_inputs var
        raw_inputs = self.inputs or {}
        raw_encrypted_inputs = self.encrypted_inputs or {}

        final_inputs = {}
        final_encrypted_inputs = {}

        for schema in self.inputs_schema or []:
            value = raw_inputs.get(schema["key"])
            encrypted_value = raw_encrypted_inputs.get(schema["key"])

            if not schema.get("secret"):
                final_inputs[schema["key"]] = value
            else:
                # We either store the incoming value if given or the encrypted value
                final_encrypted_inputs[schema["key"]] = value or encrypted_value

        self.inputs = final_inputs
        self.encrypted_inputs = final_encrypted_inputs

    @property
    def url(self):
        return absolute_uri(f"/project/{self.team_id}/pipeline/destinations/hog-{str(self.id)}")

    def save(self, *args, **kwargs):
        from posthog.cdp.filters import compile_filters_bytecode

        self.move_secret_inputs()
        if self.type in TYPES_WITH_COMPILED_FILTERS:
            self.filters = compile_filters_bytecode(self.filters, self.team)

        return super().save(*args, **kwargs)

    def __str__(self):
        return f"HogFunction {self.id}: {self.name}"


@receiver(post_save, sender=HogFunction)
def hog_function_saved(sender, instance: HogFunction, created, **kwargs):
    if instance.type is None or instance.type in TYPES_THAT_RELOAD_PLUGIN_SERVER:
        reload_hog_functions_on_workers(team_id=instance.team_id, hog_function_ids=[str(instance.id)])


@receiver(post_save, sender=Action)
def action_saved(sender, instance: Action, created, **kwargs):
    # Whenever an action is saved we want to load all hog functions using it
    # and trigger a refresh of the filters bytecode

    from posthog.tasks.hog_functions import refresh_affected_hog_functions

    refresh_affected_hog_functions.delay(action_id=instance.id)


@receiver(post_save, sender=Team)
def team_saved(sender, instance: Team, created, **kwargs):
    from posthog.tasks.hog_functions import refresh_affected_hog_functions

    refresh_affected_hog_functions.delay(team_id=instance.id)


@mutable_receiver([post_save, post_delete], sender=HogFunction)
def team_inject_web_apps_changd(sender, instance, created=None, **kwargs):
    try:
        team = instance.team
    except Team.DoesNotExist:
        team = None
    if team is not None:
        # This controls whether /decide makes extra queries to get the site apps or not
        sync_team_inject_web_apps(instance.team)
