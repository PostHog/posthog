from django.db import models

from posthog.models.utils import UUIDTModel


class TicketAssignment(UUIDTModel):
    ticket = models.OneToOneField("conversations.Ticket", on_delete=models.CASCADE, related_name="assignment")
    user = models.ForeignKey("posthog.User", null=True, on_delete=models.CASCADE)
    role = models.ForeignKey("ee.Role", null=True, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "posthog_conversations_ticket_assignment"
        constraints = [
            models.CheckConstraint(
                check=(
                    models.Q(user__isnull=False, role__isnull=True) | models.Q(user__isnull=True, role__isnull=False)
                ),
                name="exactly_one_assignee_type",
            ),
        ]
