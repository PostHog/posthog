from django.db import models

from posthog.models.team import Team


class TeamConversationsTicketConfig(models.Model):
    """Per-team ticket state. Lives on a Team extension so posthog_team is never ALTERed."""

    # db_constraint=False: a real FK constraint takes SHARE ROW EXCLUSIVE on posthog_team while
    # migrating, stalling writes under traffic.
    team = models.OneToOneField(Team, on_delete=models.CASCADE, primary_key=True, db_constraint=False, related_name="+")

    # Ticket links and Slack deep links resolve by number. Once a purge removes the highest
    # ticket, its number must stay taken, or an old link opens a different conversation.
    retired_ticket_number = models.PositiveIntegerField(
        default=0,
        db_default=0,
        help_text="Highest ticket number that a purged ticket held. New tickets always get a higher number.",
    )

    class Meta:
        app_label = "conversations"
        db_table = "posthog_conversations_ticket_config"
