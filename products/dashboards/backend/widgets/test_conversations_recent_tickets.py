from datetime import datetime, timedelta

from posthog.test.base import BaseTest

from django.utils import timezone

from products.conversations.backend.models import Ticket, TicketAssignment
from products.dashboards.backend.widget_availability import get_widget_feature_enabled
from products.dashboards.backend.widget_specs.registry import get_widget_registry_entry


class TestConversationsRecentTicketsWidget(BaseTest):
    def _ticket(
        self,
        number: int,
        status: str,
        updated_at_offset: int,
        *,
        priority: str | None = None,
        channel_source: str = "widget",
        anonymous_traits: dict[str, str] | None = None,
        sla_due_at: datetime | None = None,
    ) -> Ticket:
        ticket = Ticket.objects.create(
            team=self.team,
            ticket_number=number,
            widget_session_id=f"session-{number}",
            distinct_id=f"person-{number}",
            status=status,
            priority=priority,
            channel_source=channel_source,
            anonymous_traits=anonymous_traits or {},
            last_message_text=f"Message {number}",
            sla_due_at=sla_due_at,
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

    def test_composes_priority_channel_assignee_and_requester_search_filters(self) -> None:
        sla_due_at = timezone.now() + timedelta(hours=4)
        matching = self._ticket(
            1,
            "open",
            1,
            priority="high",
            channel_source="email",
            anonymous_traits={"name": "Jordan Lee", "email": "requester@example.com"},
            sla_due_at=sla_due_at,
        )
        TicketAssignment.objects.create(ticket=matching, user=self.user)
        self._ticket(
            2,
            "open",
            2,
            priority="low",
            channel_source="email",
            anonymous_traits={"email": "requester@example.com"},
        )

        entry = get_widget_registry_entry("conversations_recent_tickets")
        assert entry is not None
        with self.assertNumQueries(1):
            result = entry["query_fn"](
                self.team,
                {
                    "limit": 10,
                    "status": "all",
                    "priorities": ["high"],
                    "channel": "email",
                    "assignees": [{"type": "user", "id": self.user.id}],
                    "search": "requester@example.com",
                },
                None,
            )

        assert [row["id"] for row in result["results"]] == [str(matching.id)]
        assert result["results"][0]["assignee"]["user"]["id"] == self.user.id
        assert result["results"][0]["requester_name"] == "Jordan Lee"
        assert result["results"][0]["requester_email"] == "requester@example.com"
        assert result["results"][0]["sla_due_at"] == sla_due_at.isoformat()

    def test_reports_conversations_availability(self) -> None:
        self.team.conversations_enabled = False
        assert get_widget_feature_enabled("conversations_recent_tickets", self.team) is False

        self.team.conversations_enabled = True
        assert get_widget_feature_enabled("conversations_recent_tickets", self.team) is True
