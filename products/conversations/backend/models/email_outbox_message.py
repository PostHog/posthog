from django.db import models
from django.utils import timezone

from posthog.models.utils import UUIDModel

from .ticket import Ticket


class EmailOutboxMessage(UUIDModel):
    """Durable outbox for outbound email replies.

    The source of truth for whether an agent's reply has been delivered. A row is
    created in the same transaction as the reply comment, so it survives a broker
    outage; a periodic sweeper re-drives non-terminal rows until they send or hit
    the age cutoff. This is what lets outbound replies survive a multi-day Mailgun
    block instead of being dropped after a handful of broker-parked retries.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SENT = "sent", "Sent"
        FAILED_PERMANENT = "failed_permanent", "Failed (permanent)"

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE)
    # One outbox row per agent reply comment — the idempotency key across retries.
    comment = models.OneToOneField("posthog.Comment", on_delete=models.CASCADE)

    # Stable Message-ID for the outbound email, generated once and reused on every
    # attempt so threading headers and dedup stay consistent across resends.
    message_id = models.CharField(max_length=255)

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    attempts = models.PositiveIntegerField(default=0)
    last_error = models.TextField(blank=True, default="")

    # Scheduler key — the sweeper picks up pending rows whose next_attempt_at has passed.
    next_attempt_at = models.DateTimeField(default=timezone.now)
    # Lightweight lease so the immediate task and the sweeper don't double-send.
    locked_until = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        app_label = "conversations"
        db_table = "posthog_conversations_email_outbox_message"
        indexes = [
            # Sweeper query: pending rows due for an attempt, oldest first.
            models.Index(fields=["status", "next_attempt_at"], name="posthog_con_outbox_due_idx"),
        ]

    def __str__(self) -> str:
        return f"EmailOutboxMessage({self.message_id} -> ticket={self.ticket_id}, status={self.status})"
