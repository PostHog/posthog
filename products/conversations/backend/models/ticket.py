from django.db import models

from posthog.models.utils import UUIDTModel

from .constants import Channel, Priority, Status


class Ticket(UUIDTModel):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    channel_source = models.CharField(max_length=20, choices=Channel.choices, default=Channel.WIDGET)
    widget_session_id = models.CharField(max_length=64, db_index=True)  # Random UUID for access control
    distinct_id = models.CharField(max_length=400)  # PostHog distinct_id for Person linking only
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.NEW)
    priority = models.CharField(max_length=20, choices=Priority.choices, null=True, blank=True)
    assigned_to = models.ForeignKey("posthog.User", on_delete=models.SET_NULL, null=True, blank=True)
    anonymous_traits = models.JSONField(default=dict, blank=True)
    ai_resolved = models.BooleanField(default=False)
    escalation_reason = models.TextField(null=True, blank=True)

    # Unread message counters
    unread_customer_count = models.IntegerField(default=0)  # Messages customer hasn't seen (from team/AI)
    unread_team_count = models.IntegerField(default=0)  # Messages team hasn't seen (from customer)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "posthog_conversations_ticket"
        indexes = [
            models.Index(fields=["team", "widget_session_id"]),  # Access control queries
            models.Index(fields=["team", "distinct_id"]),  # Person linking queries
            models.Index(fields=["team", "status"]),
        ]

    def __str__(self):
        return f"Ticket {self.id} - {self.widget_session_id[:8]}..."
