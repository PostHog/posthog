from __future__ import annotations

from django.conf import settings
from django.db import models

from posthog.models.scoping.manager import EnvironmentScopedManager
from posthog.models.utils import UUIDModel


class TicketTopicOverrideKind(models.TextChoices):
    MUTE = "mute", "Mute"
    WATCH = "watch", "Watch"


class TicketTopicOverride(UUIDModel):
    """A person's standing instruction about one topic: never open a pattern for it, or open one at
    the lowest bar. The only thing a human authors in pattern detection; everything else is learned.

    Environment-scoped like the pattern rows it steers."""

    objects = EnvironmentScopedManager()

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False, related_name="+")
    kind = models.CharField(max_length=8, choices=TicketTopicOverrideKind.choices)
    topic = models.CharField(max_length=200)
    notes = models.CharField(max_length=500, blank=True, default="")
    enabled = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_constraint=False,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "posthog_conversations_ticket_topic_override"
        constraints = [
            models.UniqueConstraint(fields=["team", "topic"], name="conv_topic_override_unique"),
        ]

    def __str__(self) -> str:
        return f"{self.kind} {self.topic} (team {self.team_id})"
