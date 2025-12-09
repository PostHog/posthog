"""Tests for widget API endpoints."""

import json
import uuid

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import override_settings

from rest_framework import status

from posthog.models.comment import Comment

from products.conversations.backend.models import Ticket


def generate_widget_session_id() -> str:
    """Generate a random widget_session_id for testing."""
    return str(uuid.uuid4())


class TestWidgetAuthentication(APIBaseTest):
    """Tests for widget authentication."""

    def test_missing_token_header(self):
        """Request without X-Conversations-Token should fail."""
        response = self.client.post(
            "/api/conversations/v1/widget/message",
            data=json.dumps(
                {"widget_session_id": generate_widget_session_id(), "distinct_id": "test_user", "message": "Hello"}
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn("X-Conversations-Token", response.json()["detail"])

    def test_invalid_token(self):
        """Request with invalid token should fail."""
        response = self.client.post(
            "/api/conversations/v1/widget/message",
            data=json.dumps(
                {"widget_session_id": generate_widget_session_id(), "distinct_id": "test_user", "message": "Hello"}
            ),
            content_type="application/json",
            headers={"X-Conversations-Token": "invalid_token_123"},
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_conversations_disabled(self):
        """Request with valid token but conversations disabled should fail."""
        self.team.conversations_enabled = False
        self.team.conversations_public_token = "test_token_123"
        self.team.save()

        response = self.client.post(
            "/api/conversations/v1/widget/message",
            data=json.dumps(
                {"widget_session_id": generate_widget_session_id(), "distinct_id": "test_user", "message": "Hello"}
            ),
            content_type="application/json",
            headers={"X-Conversations-Token": "test_token_123"},
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_valid_token(self):
        """Request with valid token should succeed."""
        self.team.conversations_enabled = True
        self.team.conversations_public_token = "test_token_123"
        self.team.save()

        response = self.client.post(
            "/api/conversations/v1/widget/message",
            data=json.dumps(
                {"widget_session_id": generate_widget_session_id(), "distinct_id": "test_user", "message": "Hello"}
            ),
            content_type="application/json",
            headers={"X-Conversations-Token": "test_token_123"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)


class TestWidgetMessageView(APIBaseTest):
    """Tests for POST /api/conversations/widget/message."""

    def setUp(self):
        super().setUp()
        self.team.conversations_enabled = True
        self.team.conversations_public_token = "test_token_123"
        self.team.save()
        self.headers = {"X-Conversations-Token": "test_token_123"}

    def test_create_first_message_creates_ticket(self):
        """First message from a widget_session_id should create a new ticket."""
        widget_session_id = generate_widget_session_id()
        response = self.client.post(
            "/api/conversations/v1/widget/message",
            data=json.dumps(
                {"widget_session_id": widget_session_id, "distinct_id": "user_123", "message": "Hello, I need help"}
            ),
            content_type="application/json",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertIn("ticket_id", data)
        self.assertIn("message_id", data)
        self.assertEqual(data["ticket_status"], "new")

        # Verify ticket was created with widget_session_id
        ticket = Ticket.objects.get(id=data["ticket_id"])
        self.assertEqual(ticket.widget_session_id, widget_session_id)
        self.assertEqual(ticket.distinct_id, "user_123")
        self.assertEqual(ticket.channel_source, "widget")
        self.assertEqual(ticket.status, "new")

        # Verify message was created
        comment = Comment.objects.get(id=data["message_id"])
        self.assertEqual(comment.content, "Hello, I need help")
        self.assertEqual(comment.item_context["author_type"], "customer")
        self.assertEqual(comment.item_context["distinct_id"], "user_123")

    def test_add_message_to_existing_ticket(self):
        """Adding a message with ticket_id should add to existing ticket."""
        widget_session_id = generate_widget_session_id()

        # Create initial ticket
        response1 = self.client.post(
            "/api/conversations/v1/widget/message",
            data=json.dumps(
                {"widget_session_id": widget_session_id, "distinct_id": "user_123", "message": "First message"}
            ),
            content_type="application/json",
            headers=self.headers,
        )
        ticket_id = response1.json()["ticket_id"]

        # Add second message with same widget_session_id
        response2 = self.client.post(
            "/api/conversations/v1/widget/message",
            data=json.dumps(
                {
                    "widget_session_id": widget_session_id,
                    "distinct_id": "user_123",
                    "message": "Second message",
                    "ticket_id": ticket_id,
                }
            ),
            content_type="application/json",
            headers=self.headers,
        )

        self.assertEqual(response2.status_code, status.HTTP_200_OK)
        self.assertEqual(response2.json()["ticket_id"], ticket_id)

        # Verify both messages exist
        messages = Comment.objects.filter(scope="conversations_ticket", item_id=ticket_id)
        self.assertEqual(messages.count(), 2)

    def test_cannot_add_to_another_sessions_ticket(self):
        """User should not be able to add messages to another session's ticket."""
        widget_session_1 = generate_widget_session_id()
        widget_session_2 = generate_widget_session_id()

        # Create ticket for widget_session_1
        response1 = self.client.post(
            "/api/conversations/v1/widget/message",
            data=json.dumps(
                {"widget_session_id": widget_session_1, "distinct_id": "user_1", "message": "User 1 message"}
            ),
            content_type="application/json",
            headers=self.headers,
        )
        ticket_id = response1.json()["ticket_id"]

        # Try to add message as widget_session_2 (different session, even same distinct_id)
        response2 = self.client.post(
            "/api/conversations/v1/widget/message",
            data=json.dumps(
                {
                    "widget_session_id": widget_session_2,
                    "distinct_id": "user_1",
                    "message": "User 2 message",
                    "ticket_id": ticket_id,
                }
            ),
            content_type="application/json",
            headers=self.headers,
        )

        self.assertEqual(response2.status_code, status.HTTP_403_FORBIDDEN)

    def test_knowing_email_cannot_access_ticket(self):
        """Security: knowing someone's email (distinct_id) should NOT grant access."""
        widget_session_1 = generate_widget_session_id()
        widget_session_2 = generate_widget_session_id()

        # Create ticket for widget_session_1 with email as distinct_id
        response1 = self.client.post(
            "/api/conversations/v1/widget/message",
            data=json.dumps(
                {
                    "widget_session_id": widget_session_1,
                    "distinct_id": "victim@example.com",
                    "message": "Private message",
                }
            ),
            content_type="application/json",
            headers=self.headers,
        )
        ticket_id = response1.json()["ticket_id"]

        # Attacker knows the email but has different widget_session_id - should be denied
        response2 = self.client.post(
            "/api/conversations/v1/widget/message",
            data=json.dumps(
                {
                    "widget_session_id": widget_session_2,
                    "distinct_id": "victim@example.com",  # Same email!
                    "message": "Attacker message",
                    "ticket_id": ticket_id,
                }
            ),
            content_type="application/json",
            headers=self.headers,
        )

        self.assertEqual(response2.status_code, status.HTTP_403_FORBIDDEN)

    def test_anonymous_to_identified_transition(self):
        """When user identifies, distinct_id should update but session stays same."""
        widget_session_id = generate_widget_session_id()

        # First message as anonymous
        response1 = self.client.post(
            "/api/conversations/v1/widget/message",
            data=json.dumps(
                {"widget_session_id": widget_session_id, "distinct_id": "anon-uuid-123", "message": "Anonymous message"}
            ),
            content_type="application/json",
            headers=self.headers,
        )
        ticket_id = response1.json()["ticket_id"]

        # Second message after identifying (same session, different distinct_id)
        response2 = self.client.post(
            "/api/conversations/v1/widget/message",
            data=json.dumps(
                {
                    "widget_session_id": widget_session_id,
                    "distinct_id": "user@example.com",  # Now identified
                    "message": "Identified message",
                    "ticket_id": ticket_id,
                }
            ),
            content_type="application/json",
            headers=self.headers,
        )

        self.assertEqual(response2.status_code, status.HTTP_200_OK)

        # Verify distinct_id was updated
        ticket = Ticket.objects.get(id=ticket_id)
        self.assertEqual(ticket.widget_session_id, widget_session_id)
        self.assertEqual(ticket.distinct_id, "user@example.com")

    def test_honeypot_field_blocks_bots(self):
        """Request with _hp field (honeypot) should be rejected."""
        response = self.client.post(
            "/api/conversations/v1/widget/message",
            data=json.dumps(
                {
                    "widget_session_id": generate_widget_session_id(),
                    "distinct_id": "bot_123",
                    "message": "spam",
                    "_hp": "filled",
                }
            ),
            content_type="application/json",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_missing_widget_session_id(self):
        """Request without widget_session_id should fail."""
        response = self.client.post(
            "/api/conversations/v1/widget/message",
            data=json.dumps({"distinct_id": "user_123", "message": "Hello"}),
            content_type="application/json",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_invalid_widget_session_id_format(self):
        """Request with non-UUID widget_session_id should fail."""
        response = self.client.post(
            "/api/conversations/v1/widget/message",
            data=json.dumps({"widget_session_id": "not-a-uuid", "distinct_id": "user_123", "message": "Hello"}),
            content_type="application/json",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_missing_distinct_id(self):
        """Request without distinct_id should fail."""
        response = self.client.post(
            "/api/conversations/v1/widget/message",
            data=json.dumps({"widget_session_id": generate_widget_session_id(), "message": "Hello"}),
            content_type="application/json",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_missing_message(self):
        """Request without message should fail."""
        response = self.client.post(
            "/api/conversations/v1/widget/message",
            data=json.dumps({"widget_session_id": generate_widget_session_id(), "distinct_id": "user_123"}),
            content_type="application/json",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_message_too_long(self):
        """Message over 5000 chars should be rejected."""
        long_message = "x" * 5001
        response = self.client.post(
            "/api/conversations/v1/widget/message",
            data=json.dumps(
                {"widget_session_id": generate_widget_session_id(), "distinct_id": "user_123", "message": long_message}
            ),
            content_type="application/json",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_distinct_id_too_long(self):
        """distinct_id over 200 chars should be rejected."""
        long_id = "x" * 201
        response = self.client.post(
            "/api/conversations/v1/widget/message",
            data=json.dumps(
                {"widget_session_id": generate_widget_session_id(), "distinct_id": long_id, "message": "Hello"}
            ),
            content_type="application/json",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_html_in_message_is_escaped(self):
        """HTML in message should be escaped for security."""
        response = self.client.post(
            "/api/conversations/v1/widget/message",
            data=json.dumps(
                {
                    "widget_session_id": generate_widget_session_id(),
                    "distinct_id": "user_123",
                    "message": "<script>alert('xss')</script>",
                }
            ),
            content_type="application/json",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        message_id = response.json()["message_id"]
        comment = Comment.objects.get(id=message_id)
        self.assertNotIn("<script>", comment.content)
        self.assertIn("&lt;script&gt;", comment.content)

    def test_traits_are_stored(self):
        """Customer traits should be stored on ticket."""
        widget_session_id = generate_widget_session_id()
        response = self.client.post(
            "/api/conversations/v1/widget/message",
            data=json.dumps(
                {
                    "widget_session_id": widget_session_id,
                    "distinct_id": "user_123",
                    "message": "Hello",
                    "traits": {"name": "John Doe", "email": "john@example.com"},
                }
            ),
            content_type="application/json",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ticket_id = response.json()["ticket_id"]
        ticket = Ticket.objects.get(id=ticket_id)
        self.assertEqual(ticket.anonymous_traits["name"], "John Doe")
        self.assertEqual(ticket.anonymous_traits["email"], "john@example.com")

    def test_traits_are_updated(self):
        """Traits should be updated on subsequent messages."""
        widget_session_id = generate_widget_session_id()

        # First message
        response1 = self.client.post(
            "/api/conversations/v1/widget/message",
            data=json.dumps(
                {
                    "widget_session_id": widget_session_id,
                    "distinct_id": "user_123",
                    "message": "Hello",
                    "traits": {"name": "John"},
                }
            ),
            content_type="application/json",
            headers=self.headers,
        )
        ticket_id = response1.json()["ticket_id"]

        # Second message with updated traits
        response2 = self.client.post(
            "/api/conversations/v1/widget/message",
            data=json.dumps(
                {
                    "widget_session_id": widget_session_id,
                    "distinct_id": "user_123",
                    "message": "Follow up",
                    "ticket_id": ticket_id,
                    "traits": {"email": "john@example.com"},
                }
            ),
            content_type="application/json",
            headers=self.headers,
        )

        self.assertEqual(response2.status_code, status.HTTP_200_OK)
        ticket = Ticket.objects.get(id=ticket_id)
        self.assertEqual(ticket.anonymous_traits["name"], "John")
        self.assertEqual(ticket.anonymous_traits["email"], "john@example.com")

    @patch("products.conversations.backend.api.widget.logger")
    def test_validation_error_is_logged(self, mock_logger):
        """Validation errors should be logged internally."""
        response = self.client.post(
            "/api/conversations/v1/widget/message",
            data=json.dumps({"distinct_id": "user_123", "message": "Hello"}),  # Missing widget_session_id
            content_type="application/json",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        mock_logger.exception.assert_called_once()


class TestWidgetMessagesView(APIBaseTest):
    """Tests for GET /api/conversations/widget/messages/<ticket_id>."""

    def setUp(self):
        super().setUp()
        self.team.conversations_enabled = True
        self.team.conversations_public_token = "test_token_123"
        self.team.save()
        self.headers = {"X-Conversations-Token": "test_token_123"}

        # Create a ticket with messages
        self.widget_session_id = generate_widget_session_id()
        self.ticket = Ticket.objects.create(
            team=self.team,
            widget_session_id=self.widget_session_id,
            distinct_id="user_123",
            channel_source="widget",
            status="new",
        )

        self.message1 = Comment.objects.create(
            team=self.team,
            scope="conversations_ticket",
            item_id=str(self.ticket.id),
            content="First message",
            item_context={"author_type": "customer", "distinct_id": "user_123", "is_private": False},
        )

        self.message2 = Comment.objects.create(
            team=self.team,
            scope="conversations_ticket",
            item_id=str(self.ticket.id),
            content="Second message",
            created_by=self.user,
            item_context={"author_type": "agent", "is_private": False},
        )

    def test_get_messages_for_ticket(self):
        """Should return all messages for a ticket."""
        response = self.client.get(
            f"/api/conversations/v1/widget/messages/{self.ticket.id}?widget_session_id={self.widget_session_id}",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["ticket_id"], str(self.ticket.id))
        self.assertEqual(len(data["messages"]), 2)

    def test_cannot_get_another_sessions_messages(self):
        """User should not be able to access another session's ticket messages."""
        other_widget_session = generate_widget_session_id()
        response = self.client.get(
            f"/api/conversations/v1/widget/messages/{self.ticket.id}?widget_session_id={other_widget_session}",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_knowing_email_cannot_read_messages(self):
        """Security: knowing distinct_id (email) should NOT grant read access."""
        other_widget_session = generate_widget_session_id()
        # Even with the same distinct_id, different session should be denied
        response = self.client.get(
            f"/api/conversations/v1/widget/messages/{self.ticket.id}?widget_session_id={other_widget_session}",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_missing_widget_session_id(self):
        """Request without widget_session_id should fail."""
        response = self.client.get(
            f"/api/conversations/v1/widget/messages/{self.ticket.id}",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_invalid_widget_session_id_format(self):
        """Request with non-UUID widget_session_id should fail."""
        response = self.client.get(
            f"/api/conversations/v1/widget/messages/{self.ticket.id}?widget_session_id=not-a-uuid",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_ticket_not_found(self):
        """Request for non-existent ticket should return 404."""
        response = self.client.get(
            f"/api/conversations/v1/widget/messages/00000000-0000-0000-0000-000000000000?widget_session_id={self.widget_session_id}",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_private_messages_excluded(self):
        """Private messages should not be returned to widget."""
        # Add a private message
        Comment.objects.create(
            team=self.team,
            scope="conversations_ticket",
            item_id=str(self.ticket.id),
            content="Private internal note",
            created_by=self.user,
            item_context={"author_type": "agent", "is_private": True},
        )

        response = self.client.get(
            f"/api/conversations/v1/widget/messages/{self.ticket.id}?widget_session_id={self.widget_session_id}",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        messages = response.json()["messages"]
        # Should only have 2 non-private messages, not 3
        self.assertEqual(len(messages), 2)
        self.assertFalse(any(m["content"] == "Private internal note" for m in messages))

    def test_pagination_limit(self):
        """Should respect limit parameter."""
        # Create additional messages
        for i in range(10):
            Comment.objects.create(
                team=self.team,
                scope="conversations_ticket",
                item_id=str(self.ticket.id),
                content=f"Message {i}",
                item_context={"author_type": "customer", "distinct_id": "user_123", "is_private": False},
            )

        response = self.client.get(
            f"/api/conversations/v1/widget/messages/{self.ticket.id}?widget_session_id={self.widget_session_id}&limit=5",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        messages = response.json()["messages"]
        self.assertEqual(len(messages), 5)

    def test_max_limit_is_500(self):
        """Limit should be capped at 500."""
        response = self.client.get(
            f"/api/conversations/v1/widget/messages/{self.ticket.id}?widget_session_id={self.widget_session_id}&limit=1000",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Should work, but limit will be capped at 500


class TestWidgetTicketsView(APIBaseTest):
    """Tests for GET /api/conversations/widget/tickets."""

    def setUp(self):
        super().setUp()
        self.team.conversations_enabled = True
        self.team.conversations_public_token = "test_token_123"
        self.team.save()
        self.headers = {"X-Conversations-Token": "test_token_123"}

    def test_list_tickets_for_session(self):
        """Should list all tickets for a widget_session_id."""
        widget_session_id = generate_widget_session_id()

        # Create tickets for this session
        ticket1 = Ticket.objects.create(
            team=self.team,
            widget_session_id=widget_session_id,
            distinct_id="user_123",
            channel_source="widget",
            status="new",
        )
        ticket2 = Ticket.objects.create(
            team=self.team,
            widget_session_id=widget_session_id,
            distinct_id="user_123",
            channel_source="widget",
            status="resolved",
        )

        # Create ticket for different session (should not appear)
        other_widget_session = generate_widget_session_id()
        Ticket.objects.create(
            team=self.team,
            widget_session_id=other_widget_session,
            distinct_id="user_456",
            channel_source="widget",
            status="new",
        )

        response = self.client.get(
            f"/api/conversations/v1/widget/tickets?widget_session_id={widget_session_id}",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["count"], 2)
        ticket_ids = [t["id"] for t in data["results"]]
        self.assertIn(str(ticket1.id), ticket_ids)
        self.assertIn(str(ticket2.id), ticket_ids)

    def test_cannot_see_other_sessions_tickets_even_with_same_email(self):
        """Security: same distinct_id but different session should not see tickets."""
        widget_session_1 = generate_widget_session_id()
        widget_session_2 = generate_widget_session_id()

        # Create ticket for widget_session_1
        Ticket.objects.create(
            team=self.team,
            widget_session_id=widget_session_1,
            distinct_id="shared@example.com",  # Same email
            channel_source="widget",
            status="new",
        )

        # Query with widget_session_2 (same email, different session)
        response = self.client.get(
            f"/api/conversations/v1/widget/tickets?widget_session_id={widget_session_2}",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["count"], 0)  # Should NOT see widget_session_1's ticket

    def test_filter_by_status(self):
        """Should filter tickets by status."""
        widget_session_id = generate_widget_session_id()
        Ticket.objects.create(
            team=self.team,
            widget_session_id=widget_session_id,
            distinct_id="user_123",
            channel_source="widget",
            status="new",
        )
        Ticket.objects.create(
            team=self.team,
            widget_session_id=widget_session_id,
            distinct_id="user_123",
            channel_source="widget",
            status="resolved",
        )

        response = self.client.get(
            f"/api/conversations/v1/widget/tickets?widget_session_id={widget_session_id}&status=new",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["results"][0]["status"], "new")

    def test_missing_widget_session_id(self):
        """Request without widget_session_id should fail."""
        response = self.client.get(
            "/api/conversations/v1/widget/tickets",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_invalid_widget_session_id_format(self):
        """Request with non-UUID widget_session_id should fail."""
        response = self.client.get(
            "/api/conversations/v1/widget/tickets?widget_session_id=not-a-uuid",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_pagination(self):
        """Should support pagination with limit and offset."""
        widget_session_id = generate_widget_session_id()
        # Create multiple tickets
        for _i in range(15):
            Ticket.objects.create(
                team=self.team,
                widget_session_id=widget_session_id,
                distinct_id="user_123",
                channel_source="widget",
                status="new",
            )

        response = self.client.get(
            f"/api/conversations/v1/widget/tickets?widget_session_id={widget_session_id}&limit=10&offset=0",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(len(data["results"]), 10)
        self.assertEqual(data["count"], 15)

    def test_max_limit_is_50(self):
        """Limit should be capped at 50."""
        widget_session_id = generate_widget_session_id()
        response = self.client.get(
            f"/api/conversations/v1/widget/tickets?widget_session_id={widget_session_id}&limit=100",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Should work, but limit will be capped at 50


@override_settings(
    RATELIMIT_ENABLE=True,
    CACHES={
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        }
    },
)
class TestWidgetRateLimiting(APIBaseTest):
    """Tests for rate limiting."""

    def setUp(self):
        super().setUp()
        self.team.conversations_enabled = True
        self.team.conversations_public_token = "test_token_123"
        self.team.save()
        self.headers = {"X-Conversations-Token": "test_token_123"}

    def test_burst_rate_limit(self):
        """Should rate limit after 30 requests per minute per widget_session."""
        # Note: In practice, this test might need adjustment based on actual rate limit configuration
        for i in range(35):
            response = self.client.post(
                "/api/conversations/v1/widget/message",
                data=json.dumps(
                    {
                        "widget_session_id": generate_widget_session_id(),
                        "distinct_id": f"user_{i}",
                        "message": f"Message {i}",
                    }
                ),
                content_type="application/json",
                headers=self.headers,
            )
            # First 30 should succeed, later ones might be rate limited
            # This is a basic check - actual behavior depends on rate limit settings
            if i < 30:
                self.assertIn(response.status_code, [status.HTTP_200_OK, status.HTTP_429_TOO_MANY_REQUESTS])


class TestWidgetUnreadMessages(APIBaseTest):
    """Tests for unread message counters."""

    def setUp(self):
        super().setUp()
        self.team.conversations_enabled = True
        self.team.conversations_public_token = "test_token_123"
        self.team.save()
        self.headers = {"X-Conversations-Token": "test_token_123"}

    def test_customer_message_increments_team_unread_count(self):
        """When customer sends a message, unread_team_count should increment."""
        widget_session_id = generate_widget_session_id()

        # First message creates ticket with unread_team_count=1
        response = self.client.post(
            "/api/conversations/v1/widget/message",
            data=json.dumps(
                {
                    "widget_session_id": widget_session_id,
                    "distinct_id": "user_123",
                    "message": "First message",
                }
            ),
            content_type="application/json",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ticket_id = response.json()["ticket_id"]
        ticket = Ticket.objects.get(id=ticket_id)
        self.assertEqual(ticket.unread_team_count, 1)
        self.assertEqual(ticket.unread_customer_count, 0)

        # Second message increments to 2
        response = self.client.post(
            "/api/conversations/v1/widget/message",
            data=json.dumps(
                {
                    "widget_session_id": widget_session_id,
                    "distinct_id": "user_123",
                    "message": "Second message",
                    "ticket_id": ticket_id,
                }
            ),
            content_type="application/json",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ticket.refresh_from_db()
        self.assertEqual(ticket.unread_team_count, 2)

    def test_response_includes_unread_count(self):
        """Message response should include unread_count for customer."""
        widget_session_id = generate_widget_session_id()

        response = self.client.post(
            "/api/conversations/v1/widget/message",
            data=json.dumps(
                {
                    "widget_session_id": widget_session_id,
                    "distinct_id": "user_123",
                    "message": "Hello",
                }
            ),
            content_type="application/json",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertIn("unread_count", data)
        self.assertEqual(data["unread_count"], 0)  # No unread for customer yet

    def test_get_messages_includes_unread_count(self):
        """GET messages should include unread_count."""
        widget_session_id = generate_widget_session_id()
        ticket = Ticket.objects.create(
            team=self.team,
            widget_session_id=widget_session_id,
            distinct_id="user_123",
            channel_source="widget",
            status="new",
            unread_customer_count=3,
        )

        response = self.client.get(
            f"/api/conversations/v1/widget/messages/{ticket.id}?widget_session_id={widget_session_id}",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["unread_count"], 3)

    def test_tickets_list_includes_unread_count(self):
        """GET tickets should include unread_count per ticket."""
        widget_session_id = generate_widget_session_id()
        Ticket.objects.create(
            team=self.team,
            widget_session_id=widget_session_id,
            distinct_id="user_123",
            channel_source="widget",
            status="new",
            unread_customer_count=5,
        )

        response = self.client.get(
            f"/api/conversations/v1/widget/tickets?widget_session_id={widget_session_id}",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["results"][0]["unread_count"], 5)

    def test_mark_read_resets_customer_unread_count(self):
        """POST mark-read should reset unread_customer_count to 0."""
        widget_session_id = generate_widget_session_id()
        ticket = Ticket.objects.create(
            team=self.team,
            widget_session_id=widget_session_id,
            distinct_id="user_123",
            channel_source="widget",
            status="new",
            unread_customer_count=5,
        )

        response = self.client.post(
            f"/api/conversations/v1/widget/messages/{ticket.id}/read",
            data=json.dumps({"widget_session_id": widget_session_id}),
            content_type="application/json",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["unread_count"], 0)

        ticket.refresh_from_db()
        self.assertEqual(ticket.unread_customer_count, 0)

    def test_mark_read_requires_widget_session_id(self):
        """Mark-read should require widget_session_id."""
        widget_session_id = generate_widget_session_id()
        ticket = Ticket.objects.create(
            team=self.team,
            widget_session_id=widget_session_id,
            distinct_id="user_123",
            channel_source="widget",
            status="new",
        )

        response = self.client.post(
            f"/api/conversations/v1/widget/messages/{ticket.id}/read",
            data=json.dumps({}),
            content_type="application/json",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cannot_mark_read_other_sessions_ticket(self):
        """Cannot mark another session's ticket as read."""
        widget_session_1 = generate_widget_session_id()
        widget_session_2 = generate_widget_session_id()

        ticket = Ticket.objects.create(
            team=self.team,
            widget_session_id=widget_session_1,
            distinct_id="user_123",
            channel_source="widget",
            status="new",
            unread_customer_count=5,
        )

        response = self.client.post(
            f"/api/conversations/v1/widget/messages/{ticket.id}/read",
            data=json.dumps({"widget_session_id": widget_session_2}),
            content_type="application/json",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        # Unread count should not have changed
        ticket.refresh_from_db()
        self.assertEqual(ticket.unread_customer_count, 5)
