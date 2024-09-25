import enum
from typing import Optional

from django.db import models
from django.db.models.signals import post_save
from django.dispatch.dispatcher import receiver
import structlog

from posthog.cdp.templates.hog_function_template import HogFunctionTemplate
from posthog.helpers.encrypted_fields import EncryptedJSONStringField
from posthog.models.action.action import Action
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


class HogFunction(UUIDModel):
    team = models.ForeignKey("Team", on_delete=models.CASCADE)
    name = models.CharField(max_length=400, null=True, blank=True)
    description = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True, blank=True)
    created_by = models.ForeignKey("User", on_delete=models.SET_NULL, null=True, blank=True)
    deleted = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)
    enabled = models.BooleanField(default=False)

    icon_url = models.TextField(null=True, blank=True)
    hog = models.TextField()
    bytecode = models.JSONField(null=True, blank=True)
    inputs_schema = models.JSONField(null=True)
    inputs = models.JSONField(null=True)
    encrypted_inputs: EncryptedJSONStringField = EncryptedJSONStringField(null=True, blank=True)

    filters = models.JSONField(null=True, blank=True)
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
        self.filters = compile_filters_bytecode(self.filters, self.team)

        return super().save(*args, **kwargs)

    def __str__(self):
        return f"HogFunction {self.id}: {self.name}"


@receiver(post_save, sender=HogFunction)
def hog_function_saved(sender, instance: HogFunction, created, **kwargs):
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
