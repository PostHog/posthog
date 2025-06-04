from typing import TYPE_CHECKING

from django.db import models
import structlog

from posthog.models.utils import UUIDModel

if TYPE_CHECKING:
    pass

logger = structlog.get_logger(__name__)


class HogFlow(UUIDModel):
    """
    Stores the version, layout and other meta information for each HogFlow
    """

    class Meta:
        indexes = [
            models.Index(fields=["status", "team"]),
            models.Index(fields=["version", "team"]),
        ]

        constraints = [
            # Unique version # per team
            models.UniqueConstraint(fields=["team", "version"], name="unique_version"),
            # todo: allow only 1 draft per flow
        ]

    class State(models.TextChoices):
        DRAFT = "draft"
        ACTIVE = "active"
        ARCHIVED = "archived"

    class ExitCondition(models.TextChoices):
        CONVERION = "exit_on_conversion"
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
    checked_out_by = models.ForeignKey(
        "User", on_delete=models.SET_NULL, null=True, blank=True, related_name="checked_out_hogflows"
    )

    trigger = models.JSONField(default=dict)
    trigger_masking = models.JSONField(default=dict)
    conversion = models.JSONField(default=dict)
    exit_condition = models.CharField(max_length=100, choices=ExitCondition.choices, default=ExitCondition.CONVERION)

    edges = models.JSONField(default=dict)
    actions = models.JSONField(default=dict)
    abort_action = models.CharField(max_length=400, null=True, blank=True)

    def __str__(self):
        return f"HogFlow {self.id}/{self.version}: {self.name}"
