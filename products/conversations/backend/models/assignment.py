from typing import Any

from django.core.exceptions import ValidationError
from django.db import models

from posthog.models.utils import UUIDTModel


class TicketAssignment(UUIDTModel):
    ticket = models.OneToOneField("conversations.Ticket", on_delete=models.CASCADE, related_name="assignment")
    user = models.ForeignKey("posthog.User", null=True, on_delete=models.CASCADE)
    role = models.ForeignKey("ee.Role", null=True, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "posthog_conversations_ticket_assignment"

    def clean(self) -> None:
        if (self.user_id is None) == (self.role_id is None):
            raise ValidationError("Exactly one of user or role must be set")

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.clean()
        super().save(*args, **kwargs)
