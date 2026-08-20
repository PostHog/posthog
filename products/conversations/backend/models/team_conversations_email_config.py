from django.db import models

from posthog.models.team import Team
from posthog.models.utils import UUIDModel

MAX_EMAIL_CONFIGS_PER_TEAM = 10
MAX_CUSTOMER_COMMUNICATION_CHANNELS_PER_TEAM = 100
MAX_PENDING_CUSTOMER_COMMUNICATION_CHANNELS_PER_OWNER = 5


class EmailChannelKind(models.TextChoices):
    SUPPORT = "support", "Support"
    CUSTOMER_COMMUNICATION = "customer_communication", "Customer communication"


class EmailChannelConnectionStatus(models.TextChoices):
    PENDING_CONFIRMATION = "pending_confirmation", "Pending confirmation"
    ACTIVE = "active", "Active"
    CONFIRMATION_EXPIRED = "confirmation_expired", "Confirmation expired"


class EmailChannel(UUIDModel):
    """An inbound forwarding address and outbound sender identity for a team."""

    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="email_channels")
    kind = models.CharField(
        max_length=32,
        choices=EmailChannelKind.choices,
        default=EmailChannelKind.SUPPORT,
        db_default=EmailChannelKind.SUPPORT,
    )
    owner = models.ForeignKey(
        "posthog.User",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        db_constraint=False,
        related_name="owned_conversations_email_channels",
    )
    connection_status = models.CharField(
        max_length=32,
        choices=EmailChannelConnectionStatus.choices,
        default=EmailChannelConnectionStatus.ACTIVE,
        db_default=EmailChannelConnectionStatus.ACTIVE,
    )

    # The random token keeps the team id out of the public forwarding address and supports rotation.
    inbound_token = models.CharField(max_length=64, unique=True, db_index=True)

    from_email = models.EmailField()
    from_name = models.CharField(max_length=255)

    domain = models.CharField(max_length=255)
    domain_verified = models.BooleanField(default=False)
    dns_records = models.JSONField(default=dict, blank=True)

    # Only support channels can be the fallback sender for tickets without an explicit channel.
    is_default = models.BooleanField(default=False)

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
            models.UniqueConstraint(
                fields=["team"],
                condition=models.Q(is_default=True),
                name="unique_default_email_channel_per_team",
            ),
            models.CheckConstraint(
                condition=models.Q(kind=EmailChannelKind.SUPPORT) | models.Q(is_default=False),
                name="email_channel_customer_not_default",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(kind=EmailChannelKind.SUPPORT, owner__isnull=True)
                    | models.Q(kind=EmailChannelKind.CUSTOMER_COMMUNICATION, owner__isnull=False)
                ),
                name="email_channel_kind_owner",
            ),
        ]
