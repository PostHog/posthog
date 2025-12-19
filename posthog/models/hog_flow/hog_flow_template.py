from typing import TYPE_CHECKING

from django.db import models

import structlog

from posthog.models.utils import UUIDTModel

if TYPE_CHECKING:
    pass

logger = structlog.get_logger(__name__)


class HogFlowTemplate(UUIDTModel):
    """
    Stores workflow templates that can be used to create new workflows.
    """

    class Meta:
        db_table = "hogflow_templates"
        indexes = [
            models.Index(fields=["team"]),
        ]

    class ExitCondition(models.TextChoices):
        CONVERSION = "exit_on_conversion"
        TRIGGER_NOT_MATCHED = "exit_on_trigger_not_matched"
        TRIGGER_NOT_MATCHED_OR_CONVERSION = "exit_on_trigger_not_matched_or_conversion"
        ONLY_AT_END = "exit_only_at_end"

    class Scope(models.TextChoices):
        """Visibility of the workflow template"""

        ONLY_TEAM = "team", "Only team"
        GLOBAL = "global", "Global"

    name = models.CharField(max_length=400)
    description = models.TextField(blank=True, default="")
    image_url = models.CharField(max_length=8201, null=True, blank=True)
    scope = models.CharField(max_length=24, choices=Scope.choices)
    team = models.ForeignKey("Team", on_delete=models.CASCADE)

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

    def __str__(self):
        return f"HogFlowTemplate {self.id}: {self.name}"
