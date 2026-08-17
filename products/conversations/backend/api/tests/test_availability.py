from posthog.test.base import APIBaseTest

from parameterized import parameterized
from rest_framework import status

from posthog.models import Organization, OrganizationMembership, User
from posthog.models.activity_logging.activity_log import Trigger

from products.conversations.backend.api.tickets import assign_ticket
from products.conversations.backend.models import AgentAvailability, Ticket, TicketAssignment
from products.conversations.backend.models.constants import Channel, Status

from ee.models.rbac.role import Role


class TestAgentAvailabilityAPI(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.agent = User.objects.create_and_join(self.organization, "agent@example.com", None)
        self.url = f"/api/organizations/{self.organization.id}/conversations/availability/"

    def _set(self, target: User, is_available: bool):
        return self.client.put(f"{self.url}{target.id}/", {"is_available": is_available})

    def test_list_reports_who_is_unavailable_and_who_set_it(self):
        AgentAvailability.objects.create(
            organization=self.organization,
            user=self.agent,
            is_available=False,
            changed_by=self.user,
        )

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.json()
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["user"]["email"], "agent@example.com")
        self.assertFalse(results[0]["is_available"])
        self.assertEqual(results[0]["changed_by"]["email"], self.user.email)

    @parameterized.expand([(True,), (False,)])
    def test_member_can_set_their_own_availability(self, is_available: bool):
        response = self._set(self.user, is_available)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["is_available"], is_available)
        self.assertEqual(
            AgentAvailability.objects.get(organization=self.organization, user=self.user).is_available,
            is_available,
        )

    def test_member_cannot_set_someone_elses_availability(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        response = self._set(self.agent, False)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(AgentAvailability.objects.filter(user=self.agent).exists())

    def test_admin_can_set_someone_elses_availability(self):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        response = self._set(self.agent, False)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        entry = AgentAvailability.objects.get(organization=self.organization, user=self.agent)
        self.assertFalse(entry.is_available)
        self.assertEqual(entry.changed_by, self.user)

    def test_cannot_set_availability_for_someone_outside_the_organization(self):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        outsider = User.objects.create_and_join(Organization.objects.create(name="Other org"), "out@example.com", None)

        response = self._set(outsider, False)

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertFalse(AgentAvailability.objects.filter(user=outsider).exists())

    def test_an_out_of_range_user_id_is_not_found(self):
        # Python ints are unbounded, so an oversized id used to reach Postgres and raise DataError.
        response = self.client.put(f"{self.url}99999999999999999999/", {"is_available": False})

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_list_does_not_leak_other_organizations(self):
        other_org = Organization.objects.create(name="Other org")
        other_org.members.add(self.user)
        AgentAvailability.objects.create(organization=other_org, user=self.user, is_available=False)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), [])


class TestUnavailableAgentsCannotBeAssigned(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.agent = User.objects.create_and_join(self.organization, "agent@example.com", None)
        self.ticket = Ticket.objects.create_with_number(
            team=self.team,
            channel_source=Channel.WIDGET,
            widget_session_id="session-1",
            distinct_id="customer-1",
            status=Status.OPEN,
        )
        self.url = f"/api/projects/{self.team.id}/conversations/tickets/{self.ticket.id}/"

    def _mark_unavailable(self, user: User) -> None:
        AgentAvailability.objects.create(organization=self.organization, user=user, is_available=False)

    def test_cannot_assign_a_ticket_to_an_unavailable_agent(self):
        self._mark_unavailable(self.agent)

        response = self.client.patch(self.url, {"assignee": {"type": "user", "id": self.agent.id}})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("unavailable", response.json()["detail"])
        self.assertFalse(TicketAssignment.objects.filter(ticket=self.ticket).exists())

    def test_an_agent_who_is_available_again_can_be_assigned(self):
        # The flag has to be readable in both directions, or coming back leaves you unassignable.
        AgentAvailability.objects.create(organization=self.organization, user=self.agent, is_available=True)

        response = self.client.patch(self.url, {"assignee": {"type": "user", "id": self.agent.id}})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(TicketAssignment.objects.get(ticket=self.ticket).user, self.agent)

    def test_can_still_edit_a_ticket_already_assigned_to_someone_now_unavailable(self):
        # The ticket UI sends the whole form on every save, so an unchanged assignee must not
        # block editing the rest of the ticket.
        TicketAssignment.objects.create(ticket=self.ticket, user=self.agent)
        self._mark_unavailable(self.agent)

        response = self.client.patch(
            self.url,
            {"priority": "high", "assignee": {"type": "user", "id": self.agent.id}},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.priority, "high")
        self.assertEqual(TicketAssignment.objects.get(ticket=self.ticket).user, self.agent)

    def test_a_rejected_assignee_leaves_the_rest_of_the_ticket_unsaved(self):
        # The assignee arrives in the same PATCH as the other fields, so a 400 must not leave the
        # status and priority changes committed behind it.
        self._mark_unavailable(self.agent)

        response = self.client.patch(
            self.url,
            {"priority": "high", "status": Status.PENDING, "assignee": {"type": "user", "id": self.agent.id}},
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.ticket.refresh_from_db()
        self.assertIsNone(self.ticket.priority)
        self.assertEqual(self.ticket.status, Status.OPEN)

    def test_the_external_ticket_api_is_not_blocked(self):
        # No acting person means a programmatic caller, which has nobody to warn. Blocking it would
        # break tokens that already assign this way.
        self._mark_unavailable(self.agent)

        assign_ticket(
            self.ticket,
            {"type": "user", "id": self.agent.id},
            self.organization,
            None,
            self.team.id,
            False,
        )

        self.assertEqual(TicketAssignment.objects.get(ticket=self.ticket).user, self.agent)

    def test_can_take_a_ticket_yourself_while_unavailable(self):
        self._mark_unavailable(self.user)

        response = self.client.patch(self.url, {"assignee": {"type": "user", "id": self.user.id}})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(TicketAssignment.objects.get(ticket=self.ticket).user, self.user)

    def test_an_automation_can_still_assign_to_an_unavailable_agent(self):
        # Workflows own routing, so they decide what to do about an unavailable assignee. Rejecting
        # them here would drop the assignment step out of the rule with nobody to tell.
        self._mark_unavailable(self.agent)

        assign_ticket(
            self.ticket,
            {"type": "user", "id": self.agent.id},
            self.organization,
            None,
            self.team.id,
            False,
            trigger=Trigger(job_type="workflow", job_id="1", payload={}),
        )

        self.assertEqual(TicketAssignment.objects.get(ticket=self.ticket).user, self.agent)

    def test_can_assign_to_a_group_whose_member_is_unavailable(self):
        # A role is a group, and the ticket is for whoever in it responds.
        self._mark_unavailable(self.agent)
        role = Role.objects.create(name="Support", organization=self.organization)

        response = self.client.patch(self.url, {"assignee": {"type": "role", "id": str(role.id)}})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(TicketAssignment.objects.get(ticket=self.ticket).role, role)
