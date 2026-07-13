from django.db import models
from django.utils import timezone

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel

from .ticket import Ticket


class EmailDeliveryEvent(TeamScopedRootMixin, UUIDModel):
    """Per-recipient delivery outcome for an outbound ticket email, as reported
    by Mailgun's delivery webhooks.

    ``EmailOutboxMessage.status = sent`` only proves Mailgun's API accepted the
    message; rows here are the proof of what happened to each envelope recipient
    after acceptance. One row per Mailgun event, deduplicated on Mailgun's
    globally unique event id so webhook retries and replays are idempotent.
    """

    class Event(models.TextChoices):
        DELIVERED = "delivered", "Delivered"
        FAILED = "failed", "Failed"
        COMPLAINED = "complained", "Complained"

    class Severity(models.TextChoices):
        PERMANENT = "permanent", "Permanent"
        TEMPORARY = "temporary", "Temporary"

    # db_constraint=False: a real FK constraint would take SHARE ROW EXCLUSIVE on the
    # hot posthog_team table on CreateModel. App-level enforcement is enough here.
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False)
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE)
    comment = models.ForeignKey("posthog.Comment", on_delete=models.CASCADE)

    # Message-ID of the outbound email, normalized to the angle-bracketed form
    # stored on EmailOutboxMessage.message_id.
    message_id = models.CharField(max_length=255)
    recipient = models.CharField(max_length=254)
    event = models.CharField(max_length=20, choices=Event.choices)
    # Only set for failed events: permanent (bounce) vs temporary (still retrying).
    severity = models.CharField(max_length=20, choices=Severity.choices, blank=True, default="")
    reason = models.TextField(blank=True, default="")

    # Mailgun's globally unique event id — the idempotency key across webhook retries.
    provider_event_id = models.CharField(max_length=128, unique=True)
    occurred_at = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "conversations"
        db_table = "posthog_conversations_email_delivery_event"
        indexes = [
            models.Index(fields=["team", "ticket", "-created_at"], name="posthog_con_delivery_tkt_idx"),
        ]

    def __str__(self) -> str:
        return f"EmailDeliveryEvent({self.event} -> {self.recipient}, message_id={self.message_id})"
