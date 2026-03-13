import logging

from django.db import models

from posthog.models.team import Team
from posthog.models.team.extensions import register_team_extension_signal

logger = logging.getLogger(__name__)


class TeamConversationsEmailConfig(models.Model):
    team = models.OneToOneField(Team, on_delete=models.CASCADE, primary_key=True)

    # Unique token in the receiving address, e.g. "a8f3b2c1" -> team-a8f3b2c1@mg.posthog.com
    inbound_token = models.CharField(max_length=64, unique=True, db_index=True)

    from_email = models.EmailField()
    from_name = models.CharField(max_length=255)

    # Domain verification for outbound SPF/DKIM
    domain = models.CharField(max_length=255)
    domain_verified = models.BooleanField(default=False)
    dns_records = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "conversations"
        db_table = "posthog_conversations_email_config"


register_team_extension_signal(TeamConversationsEmailConfig, logger=logger)
