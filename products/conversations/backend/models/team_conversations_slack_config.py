import logging

from django.db import models

from posthog.helpers.encrypted_fields import EncryptedTextField
from posthog.models.team import Team
from posthog.models.team.extensions import register_team_extension_signal

logger = logging.getLogger(__name__)


class TeamConversationsSlackConfig(models.Model):
    team = models.OneToOneField(Team, on_delete=models.CASCADE, primary_key=True)

    slack_bot_token = EncryptedTextField(max_length=500, null=True, blank=True)

    class Meta:
        app_label = "conversations"
        db_table = "posthog_conversations_slack_config"


register_team_extension_signal(TeamConversationsSlackConfig, logger=logger)
