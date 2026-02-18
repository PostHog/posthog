import uuid

from posthog.test.base import BaseTest
from unittest.mock import patch

from rest_framework import status
from rest_framework.test import APIClient

from posthog.models.comment import Comment

from products.conversations.backend.models import Ticket
from products.conversations.backend.models.constants import Status


class TestWidgetAPI(BaseTest):
    def setUp(self):
        super().setUp()
        self.widget_token = "test_widget_token_123"
        self.team.conversations_enabled = True
        self.team.conversations_settings = {"widget_public_token": self.widget_token}
        self.team.save()

        self.widget_session_id = str(uuid.uuid4())
        self.distinct_id = "user-123"

        self.client = APIClient()

    def _get_headers(self):
        return {"HTTP_X_CONVERSATIONS_TOKEN": self.widget_token}

    def test_authentication_required(self):
        response = self.client.post("/api/conversations/v1/widget/message", {"message": "Hello"})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_authentication_invalid_token(self):
        response = self.client.post(
            "/api/conversations/v1/widget/message",
            {"message": "Hello"},
            HTTP_X_CONVERSATIONS_TOKEN="invalid_token",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_authentication_conversations_disabled(self):
        self.team.conversations_enabled = False
        self.team.save()
        response = self.client.post(
            "/api/conversations/v1/widget/message",
            {"message": "Hello", "widget_session_id": self.widget_session_id, "distinct_id": self.distinct_id},
            **self._get_headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_create_message_creates_ticket(self):
        response = self.client.post(
            "/api/conversations/v1/widget/message",
            {
                "message": "Hello, I need help!",
                "widget_session_id": self.widget_session_id,
                "distinct_id": self.distinct_id,
            },
            **self._get_headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("ticket_id", response.json())
        self.assertIn("message_id", response.json())

        ticket = Ticket.objects.get(id=response.json()["ticket_id"])
        self.assertEqual(ticket.widget_session_id, self.widget_session_id)
        self.assertEqual(ticket.distinct_id, self.distinct_id)
        self.assertEqual(ticket.status, "new")
        self.assertEqual(ticket.unread_team_count, 1)

    def test_create_message_to_existing_ticket(self):
        ticket = Ticket.objects.create_with_number(
            team=self.team,
            widget_session_id=self.widget_session_id,
            distinct_id=self.distinct_id,
            channel_source="widget",
        )
        response = self.client.post(
            "/api/conversations/v1/widget/message",
            {
                "message": "Follow up message",
                "widget_session_id": self.widget_session_id,
                "distinct_id": self.distinct_id,
                "ticket_id": str(ticket.id),
            },
            **self._get_headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["ticket_id"], str(ticket.id))

    def test_create_message_updates_session_data_on_existing_ticket(self):
        ticket = Ticket.objects.create_with_number(
            team=self.team,
            widget_session_id=self.widget_session_id,
            distinct_id=self.distinct_id,
            channel_source="widget",
            session_id="old-session-id",
            session_context={"current_url": "/some-page", "replay_url": "https://app.posthog.com/replay/old"},
        )
        response = self.client.post(
            "/api/conversations/v1/widget/message",
            {
                "message": "Follow up message",
                "widget_session_id": self.widget_session_id,
                "distinct_id": self.distinct_id,
                "ticket_id": str(ticket.id),
                "session_id": "new-session-id",
                "session_context": {"replay_url": "https://app.posthog.com/replay/new"},
            },
            **self._get_headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        ticket.refresh_from_db()
        self.assertEqual(ticket.session_id, "new-session-id")
        # session_context should merge, not replace - preserves current_url while updating replay_url
        self.assertEqual(ticket.session_context["current_url"], "/some-page")
        self.assertEqual(ticket.session_context["replay_url"], "https://app.posthog.com/replay/new")

    def test_create_message_wrong_widget_session_forbidden(self):
        ticket = Ticket.objects.create_with_number(
            team=self.team,
            widget_session_id=str(uuid.uuid4()),
            distinct_id="other-user",
            channel_source="widget",
        )
        response = self.client.post(
            "/api/conversations/v1/widget/message",
            {
                "message": "Trying to access other ticket",
                "widget_session_id": self.widget_session_id,
                "distinct_id": self.distinct_id,
                "ticket_id": str(ticket.id),
            },
            **self._get_headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_create_message_missing_widget_session_id(self):
        response = self.client.post(
            "/api/conversations/v1/widget/message",
            {"message": "Hello", "distinct_id": self.distinct_id},
            **self._get_headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_message_missing_distinct_id(self):
        response = self.client.post(
            "/api/conversations/v1/widget/message",
            {"message": "Hello", "widget_session_id": self.widget_session_id},
            **self._get_headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_message_empty_content(self):
        response = self.client.post(
            "/api/conversations/v1/widget/message",
            {
                "message": "",
                "widget_session_id": self.widget_session_id,
                "distinct_id": self.distinct_id,
            },
            **self._get_headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_message_with_traits(self):
        response = self.client.post(
            "/api/conversations/v1/widget/message",
            {
                "message": "Hello",
                "widget_session_id": self.widget_session_id,
                "distinct_id": self.distinct_id,
                "traits": {"name": "John", "email": "john@example.com"},
            },
            **self._get_headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ticket = Ticket.objects.get(id=response.json()["ticket_id"])
        self.assertEqual(ticket.anonymous_traits["name"], "John")
        self.assertEqual(ticket.anonymous_traits["email"], "john@example.com")

    def test_get_messages(self):
        ticket = Ticket.objects.create_with_number(
            team=self.team,
            widget_session_id=self.widget_session_id,
            distinct_id=self.distinct_id,
            channel_source="widget",
        )
        Comment.objects.create(
            team=self.team,
            scope="conversations_ticket",
            item_id=str(ticket.id),
            content="First message",
            item_context={"author_type": "customer", "is_private": False},
        )
        Comment.objects.create(
            team=self.team,
            scope="conversations_ticket",
            item_id=str(ticket.id),
            content="Response from team",
            item_context={"author_type": "team", "is_private": False},
        )

        response = self.client.get(
            f"/api/conversations/v1/widget/messages/{ticket.id}?widget_session_id={self.widget_session_id}",
            **self._get_headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["messages"]), 2)
        self.assertEqual(response.json()["messages"][0]["content"], "First message")

    def test_get_messages_excludes_private(self):
        ticket = Ticket.objects.create_with_number(
            team=self.team,
            widget_session_id=self.widget_session_id,
            distinct_id=self.distinct_id,
            channel_source="widget",
        )
        Comment.objects.create(
            team=self.team,
            scope="conversations_ticket",
            item_id=str(ticket.id),
            content="Public message",
            item_context={"author_type": "customer", "is_private": False},
        )
        Comment.objects.create(
            team=self.team,
            scope="conversations_ticket",
            item_id=str(ticket.id),
            content="Private internal note",
            item_context={"author_type": "team", "is_private": True},
        )

        response = self.client.get(
            f"/api/conversations/v1/widget/messages/{ticket.id}?widget_session_id={self.widget_session_id}",
            **self._get_headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["messages"]), 1)
        self.assertEqual(response.json()["messages"][0]["content"], "Public message")

    def test_get_messages_does_not_expose_is_private_field(self):
        """Verify is_private field is never sent to widget, even for public messages."""
        ticket = Ticket.objects.create_with_number(
            team=self.team,
            widget_session_id=self.widget_session_id,
            distinct_id=self.distinct_id,
            channel_source="widget",
        )
        Comment.objects.create(
            team=self.team,
            scope="conversations_ticket",
            item_id=str(ticket.id),
            content="Public message",
            item_context={"author_type": "customer", "is_private": False},
        )

        response = self.client.get(
            f"/api/conversations/v1/widget/messages/{ticket.id}?widget_session_id={self.widget_session_id}",
            **self._get_headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["messages"]), 1)
        # is_private should NOT be present in the response
        self.assertNotIn("is_private", response.json()["messages"][0])

    def test_get_messages_wrong_widget_session_forbidden(self):
        ticket = Ticket.objects.create_with_number(
            team=self.team,
            widget_session_id=str(uuid.uuid4()),
            distinct_id="other-user",
            channel_source="widget",
        )
        response = self.client.get(
            f"/api/conversations/v1/widget/messages/{ticket.id}?widget_session_id={self.widget_session_id}",
            **self._get_headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_get_messages_ticket_not_found(self):
        fake_ticket_id = str(uuid.uuid4())
        response = self.client.get(
            f"/api/conversations/v1/widget/messages/{fake_ticket_id}?widget_session_id={self.widget_session_id}",
            **self._get_headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_list_tickets(self):
        ticket1 = Ticket.objects.create_with_number(
            team=self.team,
            widget_session_id=self.widget_session_id,
            distinct_id=self.distinct_id,
            channel_source="widget",
            status=Status.NEW,
        )
        ticket2 = Ticket.objects.create_with_number(
            team=self.team,
            widget_session_id=self.widget_session_id,
            distinct_id=self.distinct_id,
            channel_source="widget",
            status=Status.RESOLVED,
        )
        # Ticket from another session - should not appear
        Ticket.objects.create_with_number(
            team=self.team,
            widget_session_id=str(uuid.uuid4()),
            distinct_id="other-user",
            channel_source="widget",
        )

        response = self.client.get(
            f"/api/conversations/v1/widget/tickets?widget_session_id={self.widget_session_id}",
            **self._get_headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 2)
        ticket_ids = {t["id"] for t in response.json()["results"]}
        self.assertIn(str(ticket1.id), ticket_ids)
        self.assertIn(str(ticket2.id), ticket_ids)

    def test_list_tickets_filter_by_status(self):
        Ticket.objects.create_with_number(
            team=self.team,
            widget_session_id=self.widget_session_id,
            distinct_id=self.distinct_id,
            channel_source="widget",
            status=Status.NEW,
        )
        Ticket.objects.create_with_number(
            team=self.team,
            widget_session_id=self.widget_session_id,
            distinct_id=self.distinct_id,
            channel_source="widget",
            status=Status.RESOLVED,
        )

        response = self.client.get(
            f"/api/conversations/v1/widget/tickets?widget_session_id={self.widget_session_id}&status={Status.NEW}",
            **self._get_headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 1)
        self.assertEqual(response.json()["results"][0]["status"], Status.NEW)

    def test_mark_read(self):
        ticket = Ticket.objects.create_with_number(
            team=self.team,
            widget_session_id=self.widget_session_id,
            distinct_id=self.distinct_id,
            channel_source="widget",
            unread_customer_count=5,
        )

        response = self.client.post(
            f"/api/conversations/v1/widget/messages/{ticket.id}/read",
            {"widget_session_id": self.widget_session_id},
            **self._get_headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["unread_count"], 0)

        ticket.refresh_from_db()
        self.assertEqual(ticket.unread_customer_count, 0)

    def test_mark_read_wrong_widget_session_forbidden(self):
        ticket = Ticket.objects.create_with_number(
            team=self.team,
            widget_session_id=str(uuid.uuid4()),
            distinct_id="other-user",
            channel_source="widget",
            unread_customer_count=5,
        )

        response = self.client.post(
            f"/api/conversations/v1/widget/messages/{ticket.id}/read",
            {"widget_session_id": self.widget_session_id},
            **self._get_headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        ticket.refresh_from_db()
        self.assertEqual(ticket.unread_customer_count, 5)

    def test_honeypot_rejects_bot(self):
        response = self.client.post(
            "/api/conversations/v1/widget/message",
            {
                "message": "I am a bot",
                "widget_session_id": self.widget_session_id,
                "distinct_id": self.distinct_id,
                "_hp": "filled_by_bot",
            },
            **self._get_headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_invalid_widget_session_id_format(self):
        response = self.client.post(
            "/api/conversations/v1/widget/message",
            {
                "message": "Hello",
                "widget_session_id": "not-a-uuid",
                "distinct_id": self.distinct_id,
            },
            **self._get_headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_message_too_long(self):
        response = self.client.post(
            "/api/conversations/v1/widget/message",
            {
                "message": "x" * 6000,
                "widget_session_id": self.widget_session_id,
                "distinct_id": self.distinct_id,
            },
            **self._get_headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class TestWidgetCacheInvalidation(BaseTest):
    """Test that widget message creation invalidates unread count cache."""

    def setUp(self):
        super().setUp()
        self.widget_token = "test_widget_token_123"
        self.team.conversations_enabled = True
        self.team.conversations_settings = {"widget_public_token": self.widget_token}
        self.team.save()

        self.widget_session_id = str(uuid.uuid4())
        self.distinct_id = "user-123"

        self.client = APIClient()

    def _get_headers(self):
        return {"HTTP_X_CONVERSATIONS_TOKEN": self.widget_token}

    def test_create_message_new_ticket_invalidates_cache(self):
        with patch("products.conversations.backend.api.widget.invalidate_unread_count_cache") as mock_invalidate:
            response = self.client.post(
                "/api/conversations/v1/widget/message",
                {
                    "message": "Hello, I need help!",
                    "widget_session_id": self.widget_session_id,
                    "distinct_id": self.distinct_id,
                },
                **self._get_headers(),
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            mock_invalidate.assert_called_once_with(self.team.id)

    def test_create_message_existing_ticket_invalidates_cache(self):
        ticket = Ticket.objects.create_with_number(
            team=self.team,
            widget_session_id=self.widget_session_id,
            distinct_id=self.distinct_id,
            channel_source="widget",
        )

        with patch("products.conversations.backend.api.widget.invalidate_unread_count_cache") as mock_invalidate:
            response = self.client.post(
                "/api/conversations/v1/widget/message",
                {
                    "message": "Follow up message",
                    "widget_session_id": self.widget_session_id,
                    "distinct_id": self.distinct_id,
                    "ticket_id": str(ticket.id),
                },
                **self._get_headers(),
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            mock_invalidate.assert_called_once_with(self.team.id)
