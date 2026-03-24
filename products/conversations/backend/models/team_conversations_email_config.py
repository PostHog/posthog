from django.db import models

from posthog.models.team import Team


class TeamConversationsEmailConfig(models.Model):
    """Per-team email channel configuration.

    Unlike TeamConversationsSlackConfig, this model is NOT auto-created via
    register_team_extension_signal. Rows only exist for teams that have
    explicitly connected email (from_email and inbound_token are required).
    """

    team = models.OneToOneField(Team, on_delete=models.CASCADE, primary_key=True)

    # Inbound routing — unique token in the receiving address
    # Generated via secrets.token_hex(16) → 32 hex chars (128 bits)
    inbound_token = models.CharField(max_length=64, unique=True, db_index=True)

    # Sender identity
    from_email = models.EmailField()
    from_name = models.CharField(max_length=255)

    # Domain verification (for outbound SPF/DKIM) — populated in Stage 2
    domain = models.CharField(max_length=255)
    domain_verified = models.BooleanField(default=False)
    dns_records = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "conversations"
        db_table = "posthog_conversations_email_config"
        constraints = [
            models.UniqueConstraint(fields=["domain"], name="unique_email_domain"),
        ]
