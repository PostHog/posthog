from django.db import models

from posthog.models.utils import UUIDTModel


class HogFlowRevision(UUIDTModel):
    """
    Stores a versioned snapshot of a HogFlow's content.
    Each revision is linked to a HogFlow and has a version number.
    """

    class Meta:
        indexes = [
            models.Index(fields=["hog_flow", "version"]),
        ]
        constraints = [
            models.UniqueConstraint(fields=["team", "hog_flow", "version"], name="unique_revision_version"),
        ]

    class State(models.TextChoices):
        DRAFT = "draft"
        ACTIVE = "active"

    hog_flow = models.ForeignKey("posthog.HogFlow", on_delete=models.CASCADE, related_name="revisions")
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    version = models.IntegerField()
    status = models.CharField(max_length=20, choices=State.choices, default=State.DRAFT)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    name = models.CharField(max_length=400, null=True, blank=True)
    description = models.TextField(blank=True, default="")

    trigger = models.JSONField(default=dict)
    trigger_masking = models.JSONField(null=True, blank=True)
    conversion = models.JSONField(null=True, blank=True)
    exit_condition = models.CharField(max_length=100, default="exit_on_conversion")

    edges = models.JSONField(default=dict)
    actions = models.JSONField(default=dict)
    abort_action = models.CharField(max_length=400, null=True, blank=True)
    variables = models.JSONField(default=list, null=True, blank=True)

    billable_action_types = models.JSONField(default=list, null=True, blank=True)

    def __str__(self):
        return f"HogFlowRevision {self.hog_flow_id}/v{self.version} ({self.status})"
