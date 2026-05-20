from django.db import models

from posthog.models.team import Team
from posthog.models.utils import UUIDModel

MAX_EMAIL_CONFIGS_PER_TEAM = 10


class EmailChannel(UUIDModel):
    """Per-team email channel configuration (many-per-team).

    A team can have multiple email channels (e.g. support@, billing@).
    Each channel has its own inbound_token for routing and its own sender identity.

    The old TeamConversationsEmailConfig (one-per-team, team as PK) still exists
    in the DB and will be removed in a follow-up PR.
    """

    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="email_channels")

    # Inbound routing — unique token in the receiving address
    # Generated via secrets.token_hex(16) → 32 hex chars (128 bits)
    inbound_token = models.CharField(max_length=64, unique=True, db_index=True)

    # Sender identity
    from_email = models.EmailField()
    from_name = models.CharField(max_length=255)

    # Domain verification (for outbound SPF/DKIM)
    domain = models.CharField(max_length=255)
    domain_verified = models.BooleanField(default=False)
    dns_records = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def mark_domain_unverified(self) -> None:
        """Flip domain_verified off after Mailgun reports the domain is no longer
        registered. Single source of truth — called from the send-reply task and
        the test-send view when send_mime raises MailgunDomainNotRegistered.
        """
        self.domain_verified = False
        self.save(update_fields=["domain_verified"])

    class Meta:
        app_label = "conversations"
        db_table = "posthog_conversations_email_channel"
        constraints = [
            models.UniqueConstraint(fields=["from_email"], name="unique_email_channel_from_email"),
        ]
