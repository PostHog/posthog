from django.db import models

from posthog.models.utils import UUIDModel

from .ticket import Ticket


class EmailMessageMapping(UUIDModel):
    # TextField (not CharField) so an unbounded inbound Message-Id header can't overflow the
    # column and 500 the webhook, silently dropping the customer's email.
    message_id = models.TextField(db_index=True)
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE)
    comment = models.ForeignKey("posthog.Comment", on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "conversations"
        db_table = "posthog_conversations_email_message_mapping"
        constraints = [
            models.UniqueConstraint(fields=["message_id", "team"], name="unique_message_per_team"),
        ]

    def __str__(self) -> str:
        return f"EmailMessageMapping({self.message_id} -> ticket={self.ticket_id})"
