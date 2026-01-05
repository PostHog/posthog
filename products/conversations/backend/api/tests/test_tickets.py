from posthog.test.base import APIBaseTest

from parameterized import parameterized
from rest_framework import status

from posthog.models.comment import Comment

from products.conversations.backend.models import Ticket
from products.conversations.backend.models.constants import Channel, Priority, Status


class TestTicketAPI(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.ticket = Ticket.objects.create(
            team=self.team,
            channel_source=Channel.WIDGET,
            widget_session_id="test-session-123",
            distinct_id="user-123",
            status=Status.NEW,
        )

    def test_list_tickets(self):
        response = self.client.get(f"/api/projects/{self.team.id}/conversations/tickets/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 1)
        self.assertEqual(response.json()["results"][0]["id"], str(self.ticket.id))

    def test_list_tickets_only_returns_team_tickets(self):
        other_ticket = Ticket.objects.create(
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

    def test_retrieve_ticket(self):
        response = self.client.get(f"/api/projects/{self.team.id}/conversations/tickets/{self.ticket.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["id"], str(self.ticket.id))
        self.assertEqual(response.json()["status"], Status.NEW)

    def test_retrieve_ticket_marks_as_read(self):
        self.ticket.unread_team_count = 5
        self.ticket.save()

        response = self.client.get(f"/api/projects/{self.team.id}/conversations/tickets/{self.ticket.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["unread_team_count"], 0)

        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.unread_team_count, 0)

    @parameterized.expand(
        [
            ("status", Status.RESOLVED, Status.RESOLVED, None),
            ("priority", Priority.HIGH, Priority.HIGH, None),
            ("assigned_to", "user_id", "user_id", "user_id"),
        ]
    )
    def test_update_ticket_field(self, field_name, update_value, expected_response_value, expected_nested_field):
        # Replace placeholders with actual values
        if update_value == "user_id":
            update_value = self.user.id
        if expected_response_value == "user_id":
            expected_response_value = self.user.id

        response = self.client.patch(
            f"/api/projects/{self.team.id}/conversations/tickets/{self.ticket.id}/",
            {field_name: update_value},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()[field_name], expected_response_value)

        # Some fields have nested representations
        if expected_nested_field:
            self.assertEqual(response.json()["assigned_to_user"]["id"], self.user.id)

        # Verify database was updated (except for nested fields)
        if field_name != "assigned_to":
            self.ticket.refresh_from_db()
            self.assertEqual(getattr(self.ticket, field_name), expected_response_value)

    @parameterized.expand(
        [
            ("status", Status.NEW, "status", Status.NEW, {"status": Status.RESOLVED}),
            ("priority", Priority.HIGH, "priority", Priority.HIGH, {"priority": Priority.LOW}),
            ("channel_source", Channel.WIDGET, "channel_source", Channel.WIDGET, {"channel_source": Channel.EMAIL}),
            ("assigned_to=unassigned", None, "assigned_to", None, {"assigned_to": "user"}),
            ("assigned_to={user_id}", "user_id", "assigned_to", "user_id", {}),
            ("distinct_id=user-123", "user-123", "distinct_id", "user-123", {"distinct_id": "different-user"}),
        ]
    )
    def test_filter_tickets(
        self, filter_param, expected_value, response_field, expected_response_value, other_ticket_attrs
    ):
        """Test filtering tickets by various fields."""
        # Update self.ticket if needed
        if expected_value == "user_id":
            self.ticket.assigned_to = self.user
            self.ticket.save()
            filter_param = filter_param.format(user_id=self.user.id)
            expected_response_value = self.user.id
        elif expected_value and expected_value != "user-123":
            setattr(self.ticket, response_field, expected_value)
            self.ticket.save()

        # Create another ticket with different attributes
        if "user" in other_ticket_attrs.get("assigned_to", ""):
            other_ticket_attrs["assigned_to"] = self.user
        Ticket.objects.create(
            team=self.team,
            channel_source=Channel.WIDGET,
            widget_session_id="other-session",
            distinct_id="other-user",
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
    def test_invalid_filter_ignored(self, filter_name, invalid_value):
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
                [("Active message", False), ("Deleted message", True)],
                {"message_count": 1},
            ),
        ]
    )
    def test_message_annotations(self, test_name, messages, expected_fields):
        """Test that message-related fields are correctly annotated on tickets."""
        for content, deleted in messages:
            Comment.objects.create(
                team=self.team,
                scope="conversations_ticket",
                item_id=str(self.ticket.id),
                content=content,
                deleted=deleted,
            )

        response = self.client.get(f"/api/projects/{self.team.id}/conversations/tickets/{self.ticket.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        for field_name, expected_value in expected_fields.items():
            if expected_value == "not_none":
                self.assertIsNotNone(response.json()[field_name])
            else:
                self.assertEqual(response.json()[field_name], expected_value)

    def test_list_tickets_no_n_plus_one_queries(self):
        """Verify ticket list doesn't trigger N+1 queries for messages and assigned users."""
        # Create 10 tickets with messages and assigned users
        for i in range(10):
            ticket = Ticket.objects.create(
                team=self.team,
                channel_source=Channel.WIDGET,
                widget_session_id=f"session-{i}",
                distinct_id=f"user-{i}",
                assigned_to=self.user,
            )
            # Add 2 messages per ticket
            Comment.objects.create(
                team=self.team,
                scope="conversations_ticket",
                item_id=str(ticket.id),
                content=f"Message 1 for ticket {i}",
            )
            Comment.objects.create(
                team=self.team,
                scope="conversations_ticket",
                item_id=str(ticket.id),
                content=f"Message 2 for ticket {i}",
            )

        # Query count should be constant regardless of number of tickets:
        # 1. Load team
        # 2. Load tickets with annotations (message_count, last_message_at, last_message_text) + select_related(assigned_to)
        # If this fails, run with -v and check the actual query count, then adjust
        with self.assertNumQueries(2):
            response = self.client.get(f"/api/projects/{self.team.id}/conversations/tickets/")
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            # Should have original ticket + 10 new tickets = 11 total
            self.assertEqual(response.json()["count"], 11)
            # Verify all annotated fields are present
            for ticket_data in response.json()["results"]:
                self.assertIn("message_count", ticket_data)
                self.assertIn("last_message_at", ticket_data)
                self.assertIn("last_message_text", ticket_data)
                self.assertIn("assigned_to_user", ticket_data)
