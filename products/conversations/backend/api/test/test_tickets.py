"""Tests for tickets API endpoints."""

import uuid

from freezegun import freeze_time
from posthog.test.base import APIBaseTest

from rest_framework import status

from posthog.models.comment import Comment

from products.conversations.backend.models import Ticket


class TestTicketViewSet(APIBaseTest):
    """Tests for authenticated ticket API endpoints."""

    def setUp(self):
        super().setUp()
        self.url = f"/api/projects/{self.team.id}/conversations/tickets/"

    def test_list_tickets(self):
        """Should list all tickets for the team."""
        # Create tickets
        ticket1 = Ticket.objects.create(
            team=self.team,
            widget_session_id=str(uuid.uuid4()),
            distinct_id="user_1",
            channel_source="widget",
            status="new",
        )
        ticket2 = Ticket.objects.create(
            team=self.team,
            widget_session_id=str(uuid.uuid4()),
            distinct_id="user_2",
            channel_source="widget",
            status="open",
        )

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(len(data["results"]), 2)

        ticket_ids = [t["id"] for t in data["results"]]
        self.assertIn(str(ticket1.id), ticket_ids)
        self.assertIn(str(ticket2.id), ticket_ids)

    def test_tickets_isolated_by_team(self):
        """Should only see tickets from own team."""
        # Create ticket in current team
        ticket1 = Ticket.objects.create(
            team=self.team,
            widget_session_id=str(uuid.uuid4()),
            distinct_id="user_1",
            channel_source="widget",
            status="new",
        )

        # Create ticket in another team
        other_team = self.organization.teams.create()
        Ticket.objects.create(
            team=other_team,
            widget_session_id=str(uuid.uuid4()),
            distinct_id="user_2",
            channel_source="widget",
            status="new",
        )

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(len(data["results"]), 1)
        self.assertEqual(data["results"][0]["id"], str(ticket1.id))

    def test_retrieve_ticket(self):
        """Should retrieve a specific ticket."""
        ticket = Ticket.objects.create(
            team=self.team,
            widget_session_id=str(uuid.uuid4()),
            distinct_id="user_1",
            channel_source="widget",
            status="new",
            anonymous_traits={"name": "John Doe", "email": "john@example.com"},
        )

        response = self.client.get(f"{self.url}{ticket.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(data["id"], str(ticket.id))
        self.assertEqual(data["distinct_id"], "user_1")
        self.assertEqual(data["status"], "new")
        self.assertEqual(data["channel_source"], "widget")
        self.assertEqual(data["anonymous_traits"]["name"], "John Doe")

    def test_cannot_retrieve_ticket_from_another_team(self):
        """Should not be able to retrieve ticket from another team."""
        other_team = self.organization.teams.create()
        ticket = Ticket.objects.create(
            team=other_team,
            widget_session_id=str(uuid.uuid4()),
            distinct_id="user_1",
            channel_source="widget",
            status="new",
        )

        response = self.client.get(f"{self.url}{ticket.id}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_update_ticket_status(self):
        """Should be able to update ticket status."""
        ticket = Ticket.objects.create(
            team=self.team,
            widget_session_id=str(uuid.uuid4()),
            distinct_id="user_1",
            channel_source="widget",
            status="new",
        )

        response = self.client.patch(
            f"{self.url}{ticket.id}/",
            data={"status": "open"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        ticket.refresh_from_db()
        self.assertEqual(ticket.status, "open")

    def test_update_ticket_ai_resolved(self):
        """Should be able to update ai_resolved flag."""
        ticket = Ticket.objects.create(
            team=self.team,
            widget_session_id=str(uuid.uuid4()),
            distinct_id="user_1",
            channel_source="widget",
            status="new",
        )

        response = self.client.patch(
            f"{self.url}{ticket.id}/",
            data={"ai_resolved": True},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        ticket.refresh_from_db()
        self.assertTrue(ticket.ai_resolved)

    def test_update_ticket_escalation_reason(self):
        """Should be able to update escalation_reason."""
        ticket = Ticket.objects.create(
            team=self.team,
            widget_session_id=str(uuid.uuid4()),
            distinct_id="user_1",
            channel_source="widget",
            status="new",
        )

        response = self.client.patch(
            f"{self.url}{ticket.id}/",
            data={"escalation_reason": "customer_requested"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        ticket.refresh_from_db()
        self.assertEqual(ticket.escalation_reason, "customer_requested")

    def test_cannot_update_readonly_fields(self):
        """Should not be able to update read-only fields."""
        ticket = Ticket.objects.create(
            team=self.team,
            widget_session_id=str(uuid.uuid4()),
            distinct_id="user_1",
            channel_source="widget",
            status="new",
        )

        # Try to update read-only fields
        response = self.client.patch(
            f"{self.url}{ticket.id}/",
            data={
                "distinct_id": "hacker_attempt",
                "channel_source": "email",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Fields should not have changed
        ticket.refresh_from_db()
        self.assertEqual(ticket.distinct_id, "user_1")
        self.assertEqual(ticket.channel_source, "widget")

    def test_delete_ticket(self):
        """Should be able to delete a ticket."""
        ticket = Ticket.objects.create(
            team=self.team,
            widget_session_id=str(uuid.uuid4()),
            distinct_id="user_1",
            channel_source="widget",
            status="new",
        )

        response = self.client.delete(f"{self.url}{ticket.id}/")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        self.assertFalse(Ticket.objects.filter(id=ticket.id).exists())

    def test_filter_by_status(self):
        """Should filter tickets by status."""
        Ticket.objects.create(
            team=self.team,
            widget_session_id=str(uuid.uuid4()),
            distinct_id="user_1",
            channel_source="widget",
            status="new",
        )
        Ticket.objects.create(
            team=self.team,
            widget_session_id=str(uuid.uuid4()),
            distinct_id="user_2",
            channel_source="widget",
            status="open",
        )
        Ticket.objects.create(
            team=self.team,
            widget_session_id=str(uuid.uuid4()),
            distinct_id="user_3",
            channel_source="widget",
            status="resolved",
        )

        response = self.client.get(f"{self.url}?status=open")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(len(data["results"]), 1)
        self.assertEqual(data["results"][0]["status"], "open")

    def test_filter_by_distinct_id(self):
        """Should filter tickets by distinct_id."""
        Ticket.objects.create(
            team=self.team,
            widget_session_id=str(uuid.uuid4()),
            distinct_id="user_123",
            channel_source="widget",
            status="new",
        )
        Ticket.objects.create(
            team=self.team,
            widget_session_id=str(uuid.uuid4()),
            distinct_id="user_456",
            channel_source="widget",
            status="new",
        )
        Ticket.objects.create(
            team=self.team,
            widget_session_id=str(uuid.uuid4()),
            distinct_id="different_user",
            channel_source="widget",
            status="new",
        )

        # Should match partial distinct_id
        response = self.client.get(f"{self.url}?distinct_id=user_")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(len(data["results"]), 2)

    def test_search_by_name(self):
        """Should search tickets by customer name in traits."""
        Ticket.objects.create(
            team=self.team,
            widget_session_id=str(uuid.uuid4()),
            distinct_id="user_1",
            channel_source="widget",
            status="new",
            anonymous_traits={"name": "John Doe"},
        )
        Ticket.objects.create(
            team=self.team,
            widget_session_id=str(uuid.uuid4()),
            distinct_id="user_2",
            channel_source="widget",
            status="new",
            anonymous_traits={"name": "Jane Smith"},
        )

        response = self.client.get(f"{self.url}?search=john")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(len(data["results"]), 1)
        self.assertEqual(data["results"][0]["anonymous_traits"]["name"], "John Doe")

    def test_search_by_email(self):
        """Should search tickets by customer email in traits."""
        Ticket.objects.create(
            team=self.team,
            widget_session_id=str(uuid.uuid4()),
            distinct_id="user_1",
            channel_source="widget",
            status="new",
            anonymous_traits={"email": "john@example.com"},
        )
        Ticket.objects.create(
            team=self.team,
            widget_session_id=str(uuid.uuid4()),
            distinct_id="user_2",
            channel_source="widget",
            status="new",
            anonymous_traits={"email": "jane@example.com"},
        )

        response = self.client.get(f"{self.url}?search=john")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(len(data["results"]), 1)
        self.assertEqual(data["results"][0]["anonymous_traits"]["email"], "john@example.com")

    def test_message_count_annotation(self):
        """Should include message count in response."""
        ticket = Ticket.objects.create(
            team=self.team,
            widget_session_id=str(uuid.uuid4()),
            distinct_id="user_1",
            channel_source="widget",
            status="new",
        )

        # Create messages
        for i in range(3):
            Comment.objects.create(
                team=self.team,
                scope="conversations_ticket",
                item_id=str(ticket.id),
                content=f"Message {i}",
                item_context={"author_type": "customer"},
            )

        response = self.client.get(f"{self.url}{ticket.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(data["message_count"], 3)

    def test_last_message_at_annotation(self):
        """Should include last_message_at timestamp in response."""
        ticket = Ticket.objects.create(
            team=self.team,
            widget_session_id=str(uuid.uuid4()),
            distinct_id="user_1",
            channel_source="widget",
            status="new",
        )

        with freeze_time("2024-01-01 12:00:00"):
            Comment.objects.create(
                team=self.team,
                scope="conversations_ticket",
                item_id=str(ticket.id),
                content="First message",
                item_context={"author_type": "customer"},
            )

        with freeze_time("2024-01-02 12:00:00"):
            Comment.objects.create(
                team=self.team,
                scope="conversations_ticket",
                item_id=str(ticket.id),
                content="Last message",
                item_context={"author_type": "customer"},
            )

        response = self.client.get(f"{self.url}{ticket.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertIsNotNone(data["last_message_at"])
        self.assertIn("2024-01-02", data["last_message_at"])

    def test_last_message_text_annotation(self):
        """Should include last message text in response."""
        ticket = Ticket.objects.create(
            team=self.team,
            widget_session_id=str(uuid.uuid4()),
            distinct_id="user_1",
            channel_source="widget",
            status="new",
        )

        Comment.objects.create(
            team=self.team,
            scope="conversations_ticket",
            item_id=str(ticket.id),
            content="First message",
            item_context={"author_type": "customer"},
        )

        Comment.objects.create(
            team=self.team,
            scope="conversations_ticket",
            item_id=str(ticket.id),
            content="Last message",
            item_context={"author_type": "customer"},
        )

        response = self.client.get(f"{self.url}{ticket.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(data["last_message_text"], "Last message")

    def test_deleted_messages_excluded_from_count(self):
        """Deleted messages should not be counted."""
        ticket = Ticket.objects.create(
            team=self.team,
            widget_session_id=str(uuid.uuid4()),
            distinct_id="user_1",
            channel_source="widget",
            status="new",
        )

        # Create 2 messages, delete 1
        Comment.objects.create(
            team=self.team,
            scope="conversations_ticket",
            item_id=str(ticket.id),
            content="Active message",
            item_context={"author_type": "customer"},
        )

        Comment.objects.create(
            team=self.team,
            scope="conversations_ticket",
            item_id=str(ticket.id),
            content="Deleted message",
            item_context={"author_type": "customer"},
            deleted=True,
        )

        response = self.client.get(f"{self.url}{ticket.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(data["message_count"], 1)

    def test_ordering_by_updated_at(self):
        """Tickets should be ordered by updated_at descending."""
        with freeze_time("2024-01-01"):
            ticket1 = Ticket.objects.create(
                team=self.team,
                widget_session_id=str(uuid.uuid4()),
                distinct_id="user_1",
                channel_source="widget",
                status="new",
            )

        with freeze_time("2024-01-03"):
            ticket2 = Ticket.objects.create(
                team=self.team,
                widget_session_id=str(uuid.uuid4()),
                distinct_id="user_2",
                channel_source="widget",
                status="new",
            )

        with freeze_time("2024-01-02"):
            ticket3 = Ticket.objects.create(
                team=self.team,
                widget_session_id=str(uuid.uuid4()),
                distinct_id="user_3",
                channel_source="widget",
                status="new",
            )

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        ticket_ids = [t["id"] for t in data["results"]]

        # Should be ordered by most recent first
        self.assertEqual(ticket_ids[0], str(ticket2.id))
        self.assertEqual(ticket_ids[1], str(ticket3.id))
        self.assertEqual(ticket_ids[2], str(ticket1.id))

    def test_pagination_default_limit(self):
        """Should paginate with default limit of 100."""
        # Create 150 tickets
        for i in range(150):
            Ticket.objects.create(
                team=self.team,
                widget_session_id=str(uuid.uuid4()),
                distinct_id=f"user_{i}",
                channel_source="widget",
                status="new",
            )

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(len(data["results"]), 100)
        self.assertIsNotNone(data["next"])

    def test_pagination_custom_limit(self):
        """Should support custom limit parameter."""
        # Create 50 tickets
        for i in range(50):
            Ticket.objects.create(
                team=self.team,
                widget_session_id=str(uuid.uuid4()),
                distinct_id=f"user_{i}",
                channel_source="widget",
                status="new",
            )

        response = self.client.get(f"{self.url}?limit=25")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(len(data["results"]), 25)

    def test_pagination_offset(self):
        """Should support offset parameter."""
        # Create tickets with predictable ordering
        with freeze_time("2024-01-01"):
            ticket1 = Ticket.objects.create(
                team=self.team,
                widget_session_id=str(uuid.uuid4()),
                distinct_id="user_1",
                channel_source="widget",
                status="new",
            )

        with freeze_time("2024-01-02"):
            Ticket.objects.create(
                team=self.team,
                widget_session_id=str(uuid.uuid4()),
                distinct_id="user_2",
                channel_source="widget",
                status="new",
            )

        # Get second page (offset=1, limit=1)
        response = self.client.get(f"{self.url}?limit=1&offset=1")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(len(data["results"]), 1)
        self.assertEqual(data["results"][0]["id"], str(ticket1.id))

    def test_pagination_max_limit(self):
        """Should respect max limit of 1000."""
        # Create 1500 tickets
        for i in range(1500):
            Ticket.objects.create(
                team=self.team,
                widget_session_id=str(uuid.uuid4()),
                distinct_id=f"user_{i}",
                channel_source="widget",
                status="new",
            )

        # Try to request 2000, should be capped at 1000
        response = self.client.get(f"{self.url}?limit=2000")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(len(data["results"]), 1000)

    def test_unauthenticated_request_fails(self):
        """Unauthenticated requests should fail."""
        self.client.logout()

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_ticket_without_messages(self):
        """Ticket with no messages should have null/zero values."""
        ticket = Ticket.objects.create(
            team=self.team,
            widget_session_id=str(uuid.uuid4()),
            distinct_id="user_1",
            channel_source="widget",
            status="new",
        )

        response = self.client.get(f"{self.url}{ticket.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(data["message_count"], 0)
        self.assertIsNone(data["last_message_at"])
        self.assertIsNone(data["last_message_text"])

    def test_combined_filters(self):
        """Should support multiple filters at once."""
        Ticket.objects.create(
            team=self.team,
            widget_session_id=str(uuid.uuid4()),
            distinct_id="target_user",
            channel_source="widget",
            status="open",
            anonymous_traits={"name": "Target Person"},
        )
        Ticket.objects.create(
            team=self.team,
            widget_session_id=str(uuid.uuid4()),
            distinct_id="other_user",
            channel_source="widget",
            status="open",
            anonymous_traits={"name": "Other Person"},
        )
        Ticket.objects.create(
            team=self.team,
            widget_session_id=str(uuid.uuid4()),
            distinct_id="target_user",
            channel_source="widget",
            status="new",
            anonymous_traits={"name": "Target Person"},
        )

        # Filter by status AND distinct_id
        response = self.client.get(f"{self.url}?status=open&distinct_id=target")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(len(data["results"]), 1)
        self.assertEqual(data["results"][0]["distinct_id"], "target_user")
        self.assertEqual(data["results"][0]["status"], "open")
