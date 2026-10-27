from datetime import UTC, datetime, timedelta

from posthog.test.base import BaseTest

from posthog.models import Organization, Team, User

from products.access_control.backend.models.access_control import AccessControl
from products.access_control.backend.models.role import Role, RoleMembership
from products.conversations.backend.facade.api import list_role_sla_breaches
from products.conversations.backend.models import Status, Ticket, TicketAssignment
from products.conversations.backend.models.constants import Channel

NOW = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)
DUE_BEFORE = NOW + timedelta(hours=24)


class TestRoleSlaBreaches(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.role = Role.objects.create(name="Support", organization=self.organization)
        RoleMembership.objects.create(user=self.user, role=self.role)
        self.other_role = Role.objects.create(name="Billing", organization=self.organization)

    def _ticket(
        self, *, team: Team | None = None, status: str = Status.NEW, sla_due_at: datetime | None = None
    ) -> Ticket:
        return Ticket.objects.create_with_number(
            team=team or self.team,
            channel_source=Channel.WIDGET,
            widget_session_id=f"session-{Ticket.all_objects.count()}",
            distinct_id="user-123",
            status=status,
            sla_due_at=sla_due_at,
        )

    def test_keeps_open_tickets_on_the_viewers_roles_that_are_due_inside_the_window(self) -> None:
        later = self._ticket(sla_due_at=NOW + timedelta(hours=20))
        soon = self._ticket(sla_due_at=NOW + timedelta(hours=2))
        TicketAssignment.objects.create(ticket=soon, role=self.role)
        TicketAssignment.objects.create(ticket=later, role=self.role)
        TicketAssignment.objects.create(ticket=self._ticket(sla_due_at=NOW - timedelta(minutes=1)), role=self.role)
        TicketAssignment.objects.create(ticket=self._ticket(sla_due_at=NOW + timedelta(hours=25)), role=self.role)
        TicketAssignment.objects.create(
            ticket=self._ticket(status=Status.RESOLVED, sla_due_at=NOW + timedelta(hours=1)), role=self.role
        )
        TicketAssignment.objects.create(ticket=self._ticket(sla_due_at=NOW + timedelta(hours=1)), user=self.user)
        TicketAssignment.objects.create(ticket=self._ticket(sla_due_at=NOW + timedelta(hours=1)), role=self.other_role)
        other_team = Team.objects.create(organization=self.organization, name="Other project")
        TicketAssignment.objects.create(
            ticket=self._ticket(team=other_team, sla_due_at=NOW + timedelta(hours=1)), role=self.role
        )
        other_org = Organization.objects.create(name="Other org")
        foreign_role = Role.objects.create(name="Foreign support", organization=other_org)
        RoleMembership.objects.create(user=self.user, role=foreign_role)
        TicketAssignment.objects.create(ticket=self._ticket(sla_due_at=NOW + timedelta(hours=1)), role=foreign_role)

        result = list_role_sla_breaches(self.team.id, self.user.id, due_after=NOW, due_before=DUE_BEFORE)

        assert [(row.role_name, row.ticket_count, row.soonest_ticket_number) for row in result] == [
            ("Support", 2, soon.ticket_number)
        ]
        assert result[0].soonest_due_at == soon.sla_due_at

    def test_a_ticket_the_viewer_cannot_open_is_left_out(self) -> None:
        # Org admins bypass access control, and the rules apply only when the feature is on.
        self.organization.available_product_features = [{"key": "access_control", "name": "Access control"}]
        self.organization.save()
        member = User.objects.create_and_join(self.organization, "member@example.com", "password")
        RoleMembership.objects.create(
            user=member, role=self.role, organization_member=member.organization_memberships.get()
        )
        hidden = self._ticket(sla_due_at=NOW + timedelta(hours=1))
        visible = self._ticket(sla_due_at=NOW + timedelta(hours=2))
        TicketAssignment.objects.create(ticket=hidden, role=self.role)
        TicketAssignment.objects.create(ticket=visible, role=self.role)
        AccessControl.objects.create(resource="ticket", team=self.team, access_level="viewer")
        AccessControl.objects.create(
            resource="ticket",
            resource_id=str(hidden.id),
            organization_member=member.organization_memberships.get(),
            team=self.team,
            access_level="none",
        )

        result = list_role_sla_breaches(self.team.id, member.id, due_after=NOW, due_before=DUE_BEFORE)

        assert [(row.ticket_count, row.soonest_ticket_number) for row in result] == [(1, visible.ticket_number)]
