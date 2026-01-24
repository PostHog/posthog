from django.db import models, transaction

from posthog.models.utils import UUIDTModel

from .constants import Channel, Priority, Status


class TicketManager(models.Manager):
    def create_with_number(self, **kwargs):
        """
        Create a ticket with an auto-incrementing ticket_number.
        Uses SELECT FOR UPDATE on Team row to serialize ticket creation per team.
        """
        from posthog.models import Team

        team = kwargs.get("team")
        if not team:
            raise ValueError("team is required")

        with transaction.atomic():
            # Lock team row to serialize ticket creation for this team
            Team.objects.select_for_update().get(id=team.id)

            max_num = self.filter(team=team).aggregate(models.Max("ticket_number"))["ticket_number__max"] or 0
            kwargs["ticket_number"] = max_num + 1
            return self.create(**kwargs)


class Ticket(UUIDTModel):
    objects = TicketManager()

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    ticket_number = models.PositiveIntegerField()
    channel_source = models.CharField(max_length=20, choices=Channel.choices, default=Channel.WIDGET)
    widget_session_id = models.CharField(max_length=64, db_index=True)  # Random UUID for access control
    distinct_id = models.CharField(max_length=400)  # PostHog distinct_id for Person linking only
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.NEW)
    priority = models.CharField(max_length=20, choices=Priority.choices, null=True, blank=True)
    anonymous_traits = models.JSONField(default=dict, blank=True)
    ai_resolved = models.BooleanField(default=False)
    escalation_reason = models.TextField(null=True, blank=True)

    # Unread message counters
    unread_customer_count = models.IntegerField(default=0)  # Messages customer hasn't seen (from team/AI)
    unread_team_count = models.IntegerField(default=0)  # Messages team hasn't seen (from customer)

    # Denormalized message stats (updated via signal on Comment save)
    message_count = models.IntegerField(default=0)
    last_message_at = models.DateTimeField(null=True, blank=True)
    last_message_text = models.CharField(max_length=500, null=True, blank=True)  # Truncated preview

    # Session context (captured when ticket is created)
    session_id = models.CharField(max_length=64, null=True, blank=True)  # PostHog session ID
    session_context = models.JSONField(default=dict, blank=True)  # session_replay_url, current_url, etc.

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "posthog_conversations_ticket"
        indexes = [
            models.Index(fields=["team", "widget_session_id"]),  # Access control queries
            models.Index(fields=["team", "distinct_id"]),  # Person linking queries
            models.Index(fields=["team", "status"]),
            models.Index(fields=["team", "-ticket_number"], name="posthog_con_team_id_ticket_idx"),  # MAX() lookups
            models.Index(fields=["team", "session_id"]),  # Session context queries
            # Dashboard ordering optimization
            models.Index(fields=["team", "-updated_at"], name="posthog_con_team_updated_idx"),
            # Dashboard filtered + ordered queries
            models.Index(fields=["team", "status", "-updated_at"], name="posthog_con_status_upd_idx"),
        ]
        constraints = [
            models.UniqueConstraint(fields=["team", "ticket_number"], name="unique_ticket_number_per_team"),
        ]

    def __str__(self):
        return f"Ticket {self.id} - {self.widget_session_id[:8]}..."
