from django.db import models

from posthog.models.integration import external_issue_url
from posthog.models.utils import UUIDTModel

from .ticket import Ticket


class TicketExternalReference(UUIDTModel):
    ticket = models.ForeignKey(
        Ticket,
        on_delete=models.CASCADE,
        related_name="external_references",
    )
    integration = models.ForeignKey("posthog.Integration", on_delete=models.CASCADE, related_name="+")
    external_context = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey("posthog.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        app_label = "conversations"
        db_table = "posthog_conversations_ticketexternalreference"
        indexes = [
            models.Index(fields=["ticket", "created_at"]),
        ]

    @property
    def external_url(self) -> str:
        return external_issue_url(self.integration, self.external_context)

    @property
    def title(self) -> str:
        return (self.external_context or {}).get("title", "")

    @property
    def external_id(self) -> str:
        context = self.external_context or {}
        return str(context.get("number") or context.get("id") or context.get("key") or context.get("issue_id") or "")
