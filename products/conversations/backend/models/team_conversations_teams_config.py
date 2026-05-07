import logging

from django.db import models

from posthog.helpers.encrypted_fields import EncryptedTextField
from posthog.models.team import Team
from posthog.models.team.extensions import register_team_extension_signal

logger = logging.getLogger(__name__)


class TeamConversationsTeamsConfig(models.Model):
    team = models.OneToOneField(Team, on_delete=models.CASCADE, primary_key=True)

    teams_tenant_id = models.CharField(max_length=64, null=True, blank=True)
    teams_graph_access_token = EncryptedTextField(max_length=4000, null=True, blank=True)
    teams_graph_refresh_token = EncryptedTextField(max_length=4000, null=True, blank=True)
    teams_token_expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        app_label = "conversations"
        db_table = "posthog_conversations_teams_config"
        indexes = [
            models.Index(fields=["teams_tenant_id"], name="conv_teams_cfg_tenant_id_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["teams_tenant_id"],
                condition=models.Q(teams_tenant_id__isnull=False),
                name="unique_teams_tenant_id",
            ),
        ]


register_team_extension_signal(TeamConversationsTeamsConfig, logger=logger)
