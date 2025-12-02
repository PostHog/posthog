from django.contrib.postgres.fields import ArrayField
from django.db import models

from posthog.models.utils import UUIDTModel

from .constants import Channel


class GuidanceRule(UUIDTModel):
    """
    Behavioral rule that controls how the AI responds.
    """

    class RuleType(models.TextChoices):
        TONE = "tone", "Tone"
        ESCALATION = "escalation", "Escalation"

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    rule_type = models.CharField(max_length=20, choices=RuleType.choices)
    name = models.CharField(max_length=200)
    content = models.TextField()
    is_active = models.BooleanField(default=True)
    channels = ArrayField(
        models.CharField(max_length=20, choices=Channel.choices),
        default=list,
        blank=True,
        help_text="Channels where this rule applies. Empty means all channels.",
    )
    created_by = models.ForeignKey(
        "posthog.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_guidance_rules",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "conversations_guidance_rule"
        indexes = [
            models.Index(fields=["team", "is_active"]),
            models.Index(fields=["team", "rule_type"]),
        ]

    def __str__(self):
        return f"{self.name} ({self.rule_type})"
