from django.db import models

from posthog.models.utils import UUIDTModel

from .constants import Channel


class Ticket(UUIDTModel):
    """
    Support ticket from any channel.
    Status flow: New → Open → Pending → Resolved
    On hold can be set at any time.
    """

    class Status(models.TextChoices):
        NEW = "new", "New"
        OPEN = "open", "Open"
        PENDING = "pending", "Pending"
        ON_HOLD = "on_hold", "On hold"
        RESOLVED = "resolved", "Resolved"

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    channel_source = models.CharField(max_length=20, choices=Channel.choices, default=Channel.WIDGET)
    distinct_id = models.CharField(max_length=400)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.NEW)
    anonymous_traits = models.JSONField(default=dict, blank=True)
    ai_resolved = models.BooleanField(default=False)
    escalation_reason = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "conversations_ticket"
        indexes = [
            models.Index(fields=["team", "distinct_id"]),
            models.Index(fields=["team", "status"]),
        ]

    def __str__(self):
        return f"Ticket {self.id} - {self.distinct_id}"
