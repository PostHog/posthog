from django.db import models

from .ticket import Ticket


class EmailMessageMapping(models.Model):
    """Maps email Message-ID headers to tickets for threading and deduplication."""

    message_id = models.CharField(max_length=255, unique=True, db_index=True)
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE)
    comment = models.ForeignKey("posthog.Comment", on_delete=models.CASCADE, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "conversations"
        db_table = "posthog_conversations_email_message_mapping"
        indexes = [
            models.Index(fields=["team", "ticket"], name="conv_email_map_team_ticket_idx"),
        ]
