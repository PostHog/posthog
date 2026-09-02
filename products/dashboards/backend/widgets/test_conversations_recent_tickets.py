from datetime import datetime, timedelta

from freezegun import freeze_time
from posthog.test.base import BaseTest

from django.utils import timezone

from parameterized import parameterized

from posthog.models import Team

from products.conversations.backend.models import Ticket, TicketAssignment, TicketView
from products.dashboards.backend.widget_availability import get_widget_feature_enabled
from products.dashboards.backend.widget_specs.registry import get_widget_registry_entry, validate_widget_config


@freeze_time("2026-08-10 12:00:00")
class TestConversationsRecentTicketsWidget(BaseTest):
    @parameterized.expand(
        [
            ("invalid_user", {"type": "user", "id": "not-a-user-id"}),
            ("invalid_role", {"type": "role", "id": "not-a-role-id"}),
            ("boolean", {"type": "user", "id": True}),
        ]
    )
    def test_rejects_invalid_assignee_ids(self, _name: str, assignee: dict[str, str | bool]) -> None:
        with self.assertRaises(Exception):
            validate_widget_config("conversations_recent_tickets", {"assignees": [assignee]})

    def test_saved_view_id_validation_matches_ticket_view_short_id(self) -> None:
        validated = validate_widget_config("conversations_recent_tickets", {"savedViewId": "123456789012"})
        assert validated["savedViewId"] == "123456789012"

        with self.assertRaises(Exception):
            validate_widget_config("conversations_recent_tickets", {"savedViewId": "1234567890123"})

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

    def test_saved_view_owns_filters_and_keeps_recent_ordering(self) -> None:
        older_high = self._ticket(1, "open", 1, priority="high")
        self._ticket(2, "resolved", 3, priority="high")
        newer_high = self._ticket(3, "open", 2, priority="high")
        view = TicketView.objects.create(
            team=self.team,
            name="High priority open tickets",
            filters={
                "status": ["open"],
                "priority": ["high"],
                "sorting": {"columnKey": "ticket_number", "order": 1},
            },
        )

        entry = get_widget_registry_entry("conversations_recent_tickets")
        assert entry is not None
        result = entry["query_fn"](
            self.team,
            {"limit": 10, "status": "resolved", "savedViewId": view.short_id},
            self.user,
        )

        assert [row["id"] for row in result["results"]] == [str(newer_high.id), str(older_high.id)]

    def test_missing_or_cross_team_saved_view_falls_back_to_direct_filters(self) -> None:
        matching = self._ticket(1, "open", 1)
        self._ticket(2, "resolved", 2)
        other_team = Team.objects.create(organization=self.organization, name="Other team")
        other_view = TicketView.objects.create(
            team=other_team,
            name="Other project view",
            filters={"status": ["resolved"]},
        )

        entry = get_widget_registry_entry("conversations_recent_tickets")
        assert entry is not None
        result = entry["query_fn"](
            self.team,
            {"limit": 10, "status": "open", "savedViewId": other_view.short_id},
            self.user,
        )

        assert [row["id"] for row in result["results"]] == [str(matching.id)]

    def test_reports_conversations_availability(self) -> None:
        self.team.conversations_enabled = False
        assert get_widget_feature_enabled("conversations_recent_tickets", self.team) is False

        self.team.conversations_enabled = True
        assert get_widget_feature_enabled("conversations_recent_tickets", self.team) is True
