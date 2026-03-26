from django.db import models

from posthog.models.team import Team

MAX_EMAIL_CONFIGS_PER_TEAM = 10


class TeamConversationsEmailConfig(models.Model):
    """Per-team email channel configuration.

    A team can have multiple email configs (e.g. support@, billing@).
    Each config has its own inbound_token for routing and its own sender identity.

    Unlike TeamConversationsSlackConfig, this model is NOT auto-created via
    register_team_extension_signal. Rows only exist for teams that have
    explicitly connected email (from_email and inbound_token are required).
    """

    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="email_configs")

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

    class Meta:
        app_label = "conversations"
        db_table = "posthog_conversations_email_config"
        constraints = [
            models.UniqueConstraint(fields=["from_email"], name="unique_email_from_email"),
        ]
