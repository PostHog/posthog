from datetime import timedelta

from posthog.test.base import BaseTest

from django.utils import timezone

from products.conversations.backend.models import Ticket
from products.dashboards.backend.widget_specs.registry import get_widget_registry_entry


class TestConversationsRecentTicketsWidget(BaseTest):
    def _ticket(self, number: int, status: str, updated_at_offset: int) -> Ticket:
        ticket = Ticket.objects.create(
            team=self.team,
            ticket_number=number,
            widget_session_id=f"session-{number}",
            distinct_id=f"person-{number}",
            status=status,
            last_message_text=f"Message {number}",
        )
        Ticket.objects.filter(pk=ticket.pk).update(updated_at=timezone.now() + timedelta(minutes=updated_at_offset))
        ticket.refresh_from_db()
        return ticket

    def test_returns_recently_updated_tickets_with_status_filter(self) -> None:
        older_open = self._ticket(1, "open", 1)
        self._ticket(2, "resolved", 3)
        newer_open = self._ticket(3, "open", 2)

        entry = get_widget_registry_entry("conversations_recent_tickets")
        assert entry is not None
        result = entry["query_fn"](
            self.team,
            {"limit": 10, "status": "open"},
            self.user,
        )

        assert [row["id"] for row in result["results"]] == [str(newer_open.id), str(older_open.id)]
