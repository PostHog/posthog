from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel


class TeamConversationsTeamsChannelSync(TeamScopedRootMixin, UUIDModel):
    """Per-channel Microsoft Graph delta-sync state for shared-channel polling.

    Shared (and private) Teams channels never push ambient messages over the bot
    webhook, so we pull them from Graph's per-channel ``messages/delta`` endpoint
    on a schedule. This row tracks where each channel's delta cursor is so each
    poll only fetches messages posted since the last run.

    Kept out of ``Team.conversations_settings`` so the every-minute poller's cursor
    writes don't contend with the settings blob and survive channel add/remove.
    """

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    teams_team_id = models.CharField(max_length=255)
    channel_id = models.CharField(max_length=255)

    # Opaque Graph @odata.deltaLink for the next poll. Null until first primed.
    delta_link = models.TextField(null=True, blank=True)
    # Once True, the initial walk-to-deltaLink has completed and we ingest new
    # messages. The priming pass itself creates no tickets (no history dump).
    primed = models.BooleanField(default=False)

    last_polled_at = models.DateTimeField(null=True, blank=True)
    last_message_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "conversations"
        db_table = "posthog_conversations_teams_channel_sync"
        constraints = [
            models.UniqueConstraint(fields=["team", "channel_id"], name="unique_teams_channel_sync_per_team"),
        ]
        indexes = [
            models.Index(fields=["team"], name="conv_teams_chan_sync_team_idx"),
        ]
