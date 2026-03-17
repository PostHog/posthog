from django.db import models

from .ticket import Ticket


class EmailMessageMapping(models.Model):
    message_id = models.CharField(max_length=255, unique=True, db_index=True)
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE)
    comment = models.ForeignKey("posthog.Comment", on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "conversations"
        db_table = "posthog_conversations_email_message_mapping"

    def __str__(self) -> str:
        return f"EmailMessageMapping({self.message_id} -> ticket={self.ticket_id})"
