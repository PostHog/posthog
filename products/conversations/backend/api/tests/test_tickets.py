from posthog.test.base import APIBaseTest, BaseTest
from unittest.mock import MagicMock, patch

from django.db import transaction

from parameterized import parameterized
from rest_framework import status

from posthog.models import ActivityLog, Comment, Organization, User

from products.conversations.backend.models import Ticket, TicketAssignment
from products.conversations.backend.models.constants import Channel, Priority, Status

from ee.models.rbac.role import Role


# Patch on_commit to execute immediately in tests
def immediate_on_commit(func):
    func()


class BaseConversationsAPITest(APIBaseTest):
    feature_flag_patcher: MagicMock
    mock_feature_flag: MagicMock

    def setUp(self):
        super().setUp()
        # Enable conversations feature flag by default
        self.set_conversations_feature_flag(True)

    def tearDown(self):
        if hasattr(self, "feature_flag_patcher"):
            self.feature_flag_patcher.stop()
        super().tearDown()

    def set_conversations_feature_flag(self, enabled=True):
        if hasattr(self, "feature_flag_patcher"):
            self.feature_flag_patcher.stop()

        self.feature_flag_patcher = patch("posthoganalytics.feature_enabled")  # type: ignore[assignment]
        self.mock_feature_flag = self.feature_flag_patcher.start()

        def check_flag(flag_name, *_args, **_kwargs):
            if flag_name == "product-support":
                return enabled
            return False

        self.mock_feature_flag.side_effect = check_flag


@patch.object(transaction, "on_commit", side_effect=immediate_on_commit)
class TestTicketAPI(BaseConversationsAPITest):
    def setUp(self):
        super().setUp()
        self.ticket = Ticket.objects.create_with_number(
            team=self.team,
            channel_source=Channel.WIDGET,
            widget_session_id="test-session-123",
            distinct_id="user-123",
            status=Status.NEW,
        )

    def test_list_tickets(self, mock_on_commit):
        response = self.client.get(f"/api/projects/{self.team.id}/conversations/tickets/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 1)
        self.assertEqual(response.json()["results"][0]["id"], str(self.ticket.id))

    def test_list_tickets_only_returns_team_tickets(self, mock_on_commit):
        other_ticket = Ticket.objects.create_with_number(
            team=self.team,
            channel_source=Channel.EMAIL,
            widget_session_id="other-session",
            distinct_id="other-user",
        )
        response = self.client.get(f"/api/projects/{self.team.id}/conversations/tickets/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 2)
        ticket_ids = {t["id"] for t in response.json()["results"]}
        self.assertIn(str(self.ticket.id), ticket_ids)
        self.assertIn(str(other_ticket.id), ticket_ids)

    def test_retrieve_ticket(self, mock_on_commit):
        response = self.client.get(f"/api/projects/{self.team.id}/conversations/tickets/{self.ticket.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["id"], str(self.ticket.id))
        self.assertEqual(response.json()["status"], Status.NEW)

    def test_retrieve_ticket_marks_as_read(self, mock_on_commit):
        self.ticket.unread_team_count = 5
        self.ticket.save()

        response = self.client.get(f"/api/projects/{self.team.id}/conversations/tickets/{self.ticket.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["unread_team_count"], 0)

        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.unread_team_count, 0)

    @parameterized.expand(
        [
            ("status", Status.RESOLVED, Status.RESOLVED),
            ("priority", Priority.HIGH, Priority.HIGH),
        ]
    )
    def test_update_ticket_field(self, mock_on_commit, field_name, update_value, expected_response_value):
        response = self.client.patch(
            f"/api/projects/{self.team.id}/conversations/tickets/{self.ticket.id}/",
            {field_name: update_value},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()[field_name], expected_response_value)

        self.ticket.refresh_from_db()
        self.assertEqual(getattr(self.ticket, field_name), expected_response_value)

    @parameterized.expand(
        [
            (f"status={Status.NEW}", Status.NEW, "status", Status.NEW, {"status": Status.RESOLVED}),
            (f"priority={Priority.HIGH}", Priority.HIGH, "priority", Priority.HIGH, {"priority": Priority.LOW}),
            (
                f"channel_source={Channel.WIDGET}",
                Channel.WIDGET,
                "channel_source",
                Channel.WIDGET,
                {"channel_source": Channel.EMAIL},
            ),
            ("distinct_id=user-123", "user-123", "distinct_id", "user-123", {}),
        ]
    )
    def test_filter_tickets(
        self, mock_on_commit, filter_param, expected_value, response_field, expected_response_value, other_ticket_attrs
    ):
        """Test filtering tickets by various fields."""
        if expected_value and expected_value != "user-123":
            setattr(self.ticket, response_field, expected_value)
            self.ticket.save()

        other_channel = other_ticket_attrs.pop("channel_source", Channel.WIDGET)
        other_distinct_id = other_ticket_attrs.pop("distinct_id", "other-user")

        Ticket.objects.create_with_number(
            team=self.team,
            channel_source=other_channel,
            widget_session_id="other-session",
            distinct_id=other_distinct_id,
            **other_ticket_attrs,
        )

        response = self.client.get(f"/api/projects/{self.team.id}/conversations/tickets/?{filter_param}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 1)

        result = response.json()["results"][0]
        if expected_response_value is None:
            self.assertIsNone(result[response_field])
        else:
            self.assertEqual(result[response_field], expected_response_value)

    @parameterized.expand([("status", "invalid"), ("priority", "invalid")])
    def test_invalid_filter_ignored(self, mock_on_commit, filter_name, invalid_value):
        """Test that invalid filter values are ignored and all tickets are returned."""
        response = self.client.get(f"/api/projects/{self.team.id}/conversations/tickets/?{filter_name}={invalid_value}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 1)

    @parameterized.expand(
        [
            (
                "message_count",
                [("First message", False), ("Second message", False)],
                {"message_count": 2},
            ),
            (
                "last_message",
                [("First message", False), ("Latest message", False)],
                {"last_message_text": "Latest message", "last_message_at": "not_none"},
            ),
            (
                "deleted_messages_excluded",
                [("Active message", False), ("Deleted message", "soft_delete")],
                {"message_count": 1},
            ),
        ]
    )
    def test_message_annotations(self, mock_on_commit, test_name, messages, expected_fields):
        """Test that denormalized message stats are correctly maintained on tickets."""
        for content, should_delete in messages:
            comment = Comment.objects.create(
                team=self.team,
                scope="conversations_ticket",
                item_id=str(self.ticket.id),
                content=content,
            )
            # Soft-delete after creation (realistic flow)
            if should_delete == "soft_delete":
                comment.deleted = True
                comment.save()

        response = self.client.get(f"/api/projects/{self.team.id}/conversations/tickets/{self.ticket.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        for field_name, expected_value in expected_fields.items():
            if expected_value == "not_none":
                self.assertIsNotNone(response.json()[field_name])
            else:
                self.assertEqual(response.json()[field_name], expected_value)

    def test_list_tickets_no_n_plus_one_queries(self, mock_on_commit):
        """Verify ticket list doesn't trigger N+1 queries for assigned users.
        Message stats (message_count, last_message_at, last_message_text) are now
        denormalized on the Ticket model, so no subqueries needed.
        """
        # Create 10 tickets with messages and assignments
        for i in range(10):
            ticket = Ticket.objects.create_with_number(
                team=self.team,
                channel_source=Channel.WIDGET,
                widget_session_id=f"session-{i}",
                distinct_id=f"user-{i}",
            )
            # Assign user to ticket
            TicketAssignment.objects.create(ticket=ticket, user=self.user)
            # Add 2 messages per ticket (updates denormalized fields via signal)
            Comment.objects.create(
                team=self.team,
                scope="conversations_ticket",
                item_id=str(ticket.id),
                content=f"Message 1 for ticket {i}",
                created_by=self.user,
            )
            Comment.objects.create(
                team=self.team,
                scope="conversations_ticket",
                item_id=str(ticket.id),
                content=f"Message 2 for ticket {i}",
                created_by=self.user,
            )

        # Query count should be constant regardless of number of tickets
        # Includes: session, user, org, team, permissions, feature flag check, count query, tickets query
        # Note: message stats are denormalized, no subqueries needed
        with self.assertNumQueries(11):
            response = self.client.get(f"/api/projects/{self.team.id}/conversations/tickets/")
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            # Should have original ticket + 10 new tickets = 11 total
            self.assertEqual(response.json()["count"], 11)
            # Verify all denormalized fields are present
            for ticket_data in response.json()["results"]:
                self.assertIn("message_count", ticket_data)
                self.assertIn("last_message_at", ticket_data)
                self.assertIn("last_message_text", ticket_data)
                self.assertIn("assignee", ticket_data)

    def test_feature_flag_required(self, mock_on_commit):
        """Verify that product-support feature flag is required for API access."""
        self.set_conversations_feature_flag(False)

        endpoints = [
            (f"/api/projects/{self.team.id}/conversations/tickets/", "GET"),
            (f"/api/projects/{self.team.id}/conversations/tickets/{self.ticket.id}/", "GET"),
            (f"/api/projects/{self.team.id}/conversations/tickets/", "POST"),
            (f"/api/projects/{self.team.id}/conversations/tickets/{self.ticket.id}/", "PATCH"),
            (f"/api/projects/{self.team.id}/conversations/tickets/{self.ticket.id}/", "DELETE"),
        ]

        for url, method in endpoints:
            response = getattr(self.client, method.lower())(url, format="json")
            self.assertEqual(
                response.status_code,
                status.HTTP_403_FORBIDDEN,
                f"Failed for {method} {url}: expected 403, got {response.status_code}",
            )


class TestTicketAssignment(BaseConversationsAPITest):
    def setUp(self):
        super().setUp()
        self.ticket = Ticket.objects.create_with_number(
            team=self.team,
            channel_source=Channel.WIDGET,
            widget_session_id="test-session-123",
            distinct_id="user-123",
            status=Status.NEW,
        )
        self.role = Role.objects.create(name="Support Team", organization=self.organization)

    def test_assign_ticket_to_user(self):
        """Test assigning a ticket to a user."""
        self.assertEqual(TicketAssignment.objects.count(), 0)

        response = self.client.patch(
            f"/api/projects/{self.team.id}/conversations/tickets/{self.ticket.id}/",
            {"assignee": {"id": self.user.id, "type": "user"}},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["assignee"]["id"], self.user.id)
        self.assertEqual(response.json()["assignee"]["type"], "user")

        self.assertEqual(TicketAssignment.objects.count(), 1)
        assignment = TicketAssignment.objects.get(ticket=self.ticket)
        self.assertEqual(assignment.user_id, self.user.id)
        self.assertIsNone(assignment.role_id)

    def test_assign_ticket_to_role(self):
        """Test assigning a ticket to a role."""
        self.assertEqual(TicketAssignment.objects.count(), 0)

        response = self.client.patch(
            f"/api/projects/{self.team.id}/conversations/tickets/{self.ticket.id}/",
            {"assignee": {"id": str(self.role.id), "type": "role"}},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["assignee"]["id"], str(self.role.id))
        self.assertEqual(response.json()["assignee"]["type"], "role")

        self.assertEqual(TicketAssignment.objects.count(), 1)
        assignment = TicketAssignment.objects.get(ticket=self.ticket)
        self.assertIsNone(assignment.user_id)
        self.assertEqual(assignment.role_id, self.role.id)

    def test_update_assignment_from_user_to_role(self):
        """Test updating assignment from user to role."""
        TicketAssignment.objects.create(ticket=self.ticket, user=self.user)
        self.assertEqual(TicketAssignment.objects.count(), 1)

        response = self.client.patch(
            f"/api/projects/{self.team.id}/conversations/tickets/{self.ticket.id}/",
            {"assignee": {"id": str(self.role.id), "type": "role"}},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["assignee"]["type"], "role")

        self.assertEqual(TicketAssignment.objects.count(), 1)
        assignment = TicketAssignment.objects.get(ticket=self.ticket)
        self.assertIsNone(assignment.user_id)
        self.assertEqual(assignment.role_id, self.role.id)

    def test_remove_assignment(self):
        """Test removing assignment from ticket."""
        TicketAssignment.objects.create(ticket=self.ticket, user=self.user)
        self.assertEqual(TicketAssignment.objects.count(), 1)

        response = self.client.patch(
            f"/api/projects/{self.team.id}/conversations/tickets/{self.ticket.id}/",
            {"assignee": None},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNone(response.json()["assignee"])
        self.assertEqual(TicketAssignment.objects.count(), 0)

    def test_serialization_returns_correct_format(self):
        """Test that assignee serialization returns correct {id, type} format."""
        TicketAssignment.objects.create(ticket=self.ticket, user=self.user)

        response = self.client.get(f"/api/projects/{self.team.id}/conversations/tickets/{self.ticket.id}/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("assignee", response.json())
        self.assertEqual(response.json()["assignee"]["id"], self.user.id)
        self.assertEqual(response.json()["assignee"]["type"], "user")

    def test_unassigned_ticket_returns_null_assignee(self):
        """Test that unassigned ticket returns null for assignee."""
        response = self.client.get(f"/api/projects/{self.team.id}/conversations/tickets/{self.ticket.id}/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNone(response.json()["assignee"])

    def test_filter_by_user_assignment(self):
        """Test filtering tickets by user assignment."""
        TicketAssignment.objects.create(ticket=self.ticket, user=self.user)

        Ticket.objects.create_with_number(
            team=self.team,
            channel_source=Channel.WIDGET,
            widget_session_id="other-session",
            distinct_id="other-user",
        )

        response = self.client.get(f"/api/projects/{self.team.id}/conversations/tickets/?assignee=user:{self.user.id}")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 1)
        self.assertEqual(response.json()["results"][0]["id"], str(self.ticket.id))

    def test_filter_by_role_assignment(self):
        """Test filtering tickets by role assignment."""
        TicketAssignment.objects.create(ticket=self.ticket, role=self.role)

        Ticket.objects.create_with_number(
            team=self.team,
            channel_source=Channel.WIDGET,
            widget_session_id="other-session",
            distinct_id="other-user",
        )

        response = self.client.get(f"/api/projects/{self.team.id}/conversations/tickets/?assignee=role:{self.role.id}")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 1)
        self.assertEqual(response.json()["results"][0]["id"], str(self.ticket.id))

    def test_filter_unassigned_tickets(self):
        """Test filtering for unassigned tickets."""
        assigned_ticket = Ticket.objects.create_with_number(
            team=self.team,
            channel_source=Channel.WIDGET,
            widget_session_id="assigned-session",
            distinct_id="assigned-user",
        )
        TicketAssignment.objects.create(ticket=assigned_ticket, user=self.user)

        response = self.client.get(f"/api/projects/{self.team.id}/conversations/tickets/?assignee=unassigned")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 1)
        self.assertEqual(response.json()["results"][0]["id"], str(self.ticket.id))

    def test_assignment_logs_activity(self):
        """Test that assignment changes are logged in activity log."""
        response = self.client.patch(
            f"/api/projects/{self.team.id}/conversations/tickets/{self.ticket.id}/",
            {"assignee": {"id": self.user.id, "type": "user"}},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        activity = ActivityLog.objects.filter(
            team_id=self.team.id,
            scope="Ticket",
            item_id=str(self.ticket.id),
            activity="assigned",
        ).first()

        assert activity is not None
        assert activity.detail is not None
        self.assertEqual(activity.detail["changes"][0]["field"], "assignee")
        self.assertIsNone(activity.detail["changes"][0]["before"])
        self.assertEqual(activity.detail["changes"][0]["after"]["id"], self.user.id)
        self.assertEqual(activity.detail["changes"][0]["after"]["type"], "user")

    @parameterized.expand(
        [
            ("missing_type", {"id": 1}, "must have 'type' and 'id'"),
            ("missing_id", {"type": "user"}, "must have 'type' and 'id'"),
            ("invalid_type", {"id": 1, "type": "invalid"}, "type must be 'user' or 'role'"),
            ("not_an_object", "invalid", "must be an object"),
        ]
    )
    def test_invalid_assignee_payload(self, name, payload, expected_error):
        response = self.client.patch(
            f"/api/projects/{self.team.id}/conversations/tickets/{self.ticket.id}/",
            {"assignee": payload},
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn(expected_error, str(response.json()))

    def test_assign_to_user_not_in_organization(self):
        other_user = User.objects.create(email="other@example.com")

        response = self.client.patch(
            f"/api/projects/{self.team.id}/conversations/tickets/{self.ticket.id}/",
            {"assignee": {"id": other_user.id, "type": "user"}},
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("not a member of this organization", str(response.json()))
        self.assertEqual(TicketAssignment.objects.count(), 0)

    def test_assign_to_role_not_in_organization(self):
        other_org = Organization.objects.create(name="Other Org")
        other_role = Role.objects.create(name="Other Role", organization=other_org)

        response = self.client.patch(
            f"/api/projects/{self.team.id}/conversations/tickets/{self.ticket.id}/",
            {"assignee": {"id": str(other_role.id), "type": "role"}},
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("does not belong to this organization", str(response.json()))
        self.assertEqual(TicketAssignment.objects.count(), 0)


class TestTicketManager(BaseTest):
    def test_requires_team(self):
        with self.assertRaises(ValueError) as ctx:
            Ticket.objects.create_with_number(
                channel_source=Channel.WIDGET,
                widget_session_id="test-session",
                distinct_id="user-123",
            )
        self.assertEqual(str(ctx.exception), "team is required")

    def test_auto_increments_ticket_number(self):
        ticket1 = Ticket.objects.create_with_number(
            team=self.team,
            channel_source=Channel.WIDGET,
            widget_session_id="session-1",
            distinct_id="user-1",
        )
        ticket2 = Ticket.objects.create_with_number(
            team=self.team,
            channel_source=Channel.WIDGET,
            widget_session_id="session-2",
            distinct_id="user-2",
        )

        self.assertEqual(ticket1.ticket_number, 1)
        self.assertEqual(ticket2.ticket_number, 2)
