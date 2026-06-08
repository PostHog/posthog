import uuid

from posthog.test.base import BaseTest
from unittest.mock import patch

from rest_framework import status
from rest_framework.test import APIClient

from posthog.models.comment import Comment

from products.conversations.backend.models import Ticket
from products.conversations.backend.models.constants import ChannelDetail, Status
from products.conversations.backend.services.identity import compute_identity_hash


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
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_authentication_invalid_token(self):
        response = self.client.post(
            "/api/conversations/v1/widget/message",
            {"message": "Hello"},
            headers={"x-conversations-token": "invalid_token"},
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_authentication_conversations_disabled(self):
        self.team.conversations_enabled = False
        self.team.save()
        response = self.client.post(
            "/api/conversations/v1/widget/message",
            {"message": "Hello", "widget_session_id": self.widget_session_id, "distinct_id": self.distinct_id},
            **self._get_headers(),
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

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
        assert response.status_code == status.HTTP_200_OK
        assert "ticket_id" in response.json()
        assert "message_id" in response.json()

        ticket = Ticket.objects.get(id=response.json()["ticket_id"])
        assert ticket.widget_session_id == self.widget_session_id
        assert ticket.distinct_id == self.distinct_id
        assert ticket.status == "new"
        assert ticket.unread_team_count == 1

    def test_create_ticket_channel_detail_widget_enabled(self):
        self.team.conversations_settings = {**self.team.conversations_settings, "widget_enabled": True}
        self.team.save()
        response = self.client.post(
            "/api/conversations/v1/widget/message",
            {"message": "Hi", "widget_session_id": self.widget_session_id, "distinct_id": self.distinct_id},
            **self._get_headers(),
        )
        assert response.status_code == status.HTTP_200_OK
        ticket = Ticket.objects.get(id=response.json()["ticket_id"])
        assert ticket.channel_detail == ChannelDetail.WIDGET_EMBEDDED

    def test_create_ticket_channel_detail_widget_disabled(self):
        self.team.conversations_settings = {**self.team.conversations_settings, "widget_enabled": False}
        self.team.save()
        response = self.client.post(
            "/api/conversations/v1/widget/message",
            {"message": "Hi", "widget_session_id": str(uuid.uuid4()), "distinct_id": "user-456"},
            **self._get_headers(),
        )
        assert response.status_code == status.HTTP_200_OK
        ticket = Ticket.objects.get(id=response.json()["ticket_id"])
        assert ticket.channel_detail == ChannelDetail.WIDGET_API

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
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["ticket_id"] == str(ticket.id)

    def test_unverified_request_cannot_repoint_ticket_distinct_id(self):
        # An anonymous (widget_session_id-only) request must not be able to overwrite an
        # existing ticket's distinct_id with another identity. Otherwise an attacker who
        # owns a ticket could re-point it at a victim's distinct_id and have it surface in
        # the victim's verified history / be linked to the victim's profile for staff.
        ticket = Ticket.objects.create_with_number(
            team=self.team,
            widget_session_id=self.widget_session_id,
            distinct_id=self.distinct_id,
            channel_source="widget",
        )
        response = self.client.post(
            "/api/conversations/v1/widget/message",
            {
                "message": "Trying to hijack identity",
                "widget_session_id": self.widget_session_id,
                "distinct_id": "victim@example.com",
                "ticket_id": str(ticket.id),
            },
            **self._get_headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        ticket.refresh_from_db()
        self.assertEqual(ticket.distinct_id, self.distinct_id)

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
        assert response.status_code == status.HTTP_200_OK

        ticket.refresh_from_db()
        assert ticket.session_id == "new-session-id"
        # session_context should merge, not replace - preserves current_url while updating replay_url
        assert ticket.session_context["current_url"] == "/some-page"
        assert ticket.session_context["replay_url"] == "https://app.posthog.com/replay/new"

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
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_create_message_missing_widget_session_id(self):
        response = self.client.post(
            "/api/conversations/v1/widget/message",
            {"message": "Hello", "distinct_id": self.distinct_id},
            **self._get_headers(),
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_create_message_missing_distinct_id(self):
        response = self.client.post(
            "/api/conversations/v1/widget/message",
            {"message": "Hello", "widget_session_id": self.widget_session_id},
            **self._get_headers(),
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

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
        assert response.status_code == status.HTTP_400_BAD_REQUEST

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
        assert response.status_code == status.HTTP_200_OK
        ticket = Ticket.objects.get(id=response.json()["ticket_id"])
        assert ticket.anonymous_traits["name"] == "John"
        assert ticket.anonymous_traits["email"] == "john@example.com"

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
        assert response.status_code == status.HTTP_200_OK
        assert len(response.json()["messages"]) == 2
        assert response.json()["messages"][0]["content"] == "First message"

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
        assert response.status_code == status.HTTP_200_OK
        assert len(response.json()["messages"]) == 1
        assert response.json()["messages"][0]["content"] == "Public message"

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
        assert response.status_code == status.HTTP_200_OK
        assert len(response.json()["messages"]) == 1
        # is_private should NOT be present in the response
        assert "is_private" not in response.json()["messages"][0]

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
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_get_messages_ticket_not_found(self):
        fake_ticket_id = str(uuid.uuid4())
        response = self.client.get(
            f"/api/conversations/v1/widget/messages/{fake_ticket_id}?widget_session_id={self.widget_session_id}",
            **self._get_headers(),
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

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
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["count"] == 2
        ticket_ids = {t["id"] for t in response.json()["results"]}
        assert str(ticket1.id) in ticket_ids
        assert str(ticket2.id) in ticket_ids

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
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["count"] == 1
        assert response.json()["results"][0]["status"] == Status.NEW

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
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["unread_count"] == 0

        ticket.refresh_from_db()
        assert ticket.unread_customer_count == 0

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
        assert response.status_code == status.HTTP_403_FORBIDDEN

        ticket.refresh_from_db()
        assert ticket.unread_customer_count == 5

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
        assert response.status_code == status.HTTP_400_BAD_REQUEST

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
        assert response.status_code == status.HTTP_400_BAD_REQUEST

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
        assert response.status_code == status.HTTP_400_BAD_REQUEST


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
            assert response.status_code == status.HTTP_200_OK
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
            assert response.status_code == status.HTTP_200_OK
            mock_invalidate.assert_called_once_with(self.team.id)


class TestWidgetIdentityVerification(BaseTest):
    def setUp(self):
        super().setUp()
        self.widget_token = "test_widget_token_iv"
        self.secret = "test_secret_key_for_hmac"
        self.team.conversations_enabled = True
        self.team.conversations_settings = {
            "widget_public_token": self.widget_token,
        }
        self.team.secret_api_token = self.secret
        self.team.save()

        self.distinct_id = "user_123"
        self.identity_hash = compute_identity_hash(self.distinct_id, self.secret)
        self.widget_session_id = str(uuid.uuid4())

        self.client = APIClient()

    def _get_headers(self):
        return {"HTTP_X_CONVERSATIONS_TOKEN": self.widget_token}

    def _create_ticket(self, distinct_id=None, widget_session_id=None):
        return Ticket.objects.create_with_number(
            team=self.team,
            widget_session_id=widget_session_id or self.widget_session_id,
            distinct_id=distinct_id or self.distinct_id,
            channel_source="widget",
        )

    # --- List tickets ---

    def test_list_tickets_with_valid_identity(self):
        self._create_ticket()
        response = self.client.get(
            "/api/conversations/v1/widget/tickets",
            {
                "identity_distinct_id": self.distinct_id,
                "identity_hash": self.identity_hash,
            },
            **self._get_headers(),
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["count"] == 1

    def test_list_tickets_invalid_hash_returns_forbidden(self):
        self._create_ticket()
        response = self.client.get(
            "/api/conversations/v1/widget/tickets",
            {
                "identity_distinct_id": self.distinct_id,
                "identity_hash": "0" * 64,
            },
            **self._get_headers(),
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_list_tickets_missing_identity_fields_uses_session(self):
        self._create_ticket()
        response = self.client.get(
            "/api/conversations/v1/widget/tickets",
            {"widget_session_id": self.widget_session_id},
            **self._get_headers(),
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["count"] == 1

    def test_cross_browser_same_tickets(self):
        other_session = str(uuid.uuid4())
        self._create_ticket(widget_session_id=other_session)

        response = self.client.get(
            "/api/conversations/v1/widget/tickets",
            {
                "identity_distinct_id": self.distinct_id,
                "identity_hash": self.identity_hash,
            },
            **self._get_headers(),
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["count"] == 1

    # --- Send message ---

    def test_send_message_creates_ticket_with_identity(self):
        response = self.client.post(
            "/api/conversations/v1/widget/message",
            {
                "identity_distinct_id": self.distinct_id,
                "identity_hash": self.identity_hash,
                "message": "Hello from identity mode",
            },
            **self._get_headers(),
        )
        assert response.status_code == status.HTTP_200_OK
        ticket = Ticket.objects.get(id=response.json()["ticket_id"])
        assert ticket.distinct_id == self.distinct_id

    def test_send_message_existing_ticket_ownership_by_distinct_id(self):
        ticket = self._create_ticket()
        Comment.objects.create(
            team=self.team,
            scope="conversations_ticket",
            item_id=str(ticket.id),
            content="First message",
            item_context={"author_type": "customer"},
        )

        response = self.client.post(
            "/api/conversations/v1/widget/message",
            {
                "identity_distinct_id": self.distinct_id,
                "identity_hash": self.identity_hash,
                "message": "Follow-up via identity",
                "ticket_id": str(ticket.id),
            },
            **self._get_headers(),
        )
        assert response.status_code == status.HTTP_200_OK

    def test_send_message_invalid_hash_no_session_returns_forbidden(self):
        response = self.client.post(
            "/api/conversations/v1/widget/message",
            {
                "identity_distinct_id": self.distinct_id,
                "identity_hash": "0" * 64,
                "message": "Should be rejected",
            },
            **self._get_headers(),
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_send_message_wrong_distinct_id_returns_forbidden(self):
        ticket = self._create_ticket(distinct_id="user_123")
        other_id = "user_456"
        other_hash = compute_identity_hash(other_id, self.secret)

        response = self.client.post(
            "/api/conversations/v1/widget/message",
            {
                "identity_distinct_id": other_id,
                "identity_hash": other_hash,
                "message": "Trying to access another user's ticket",
                "ticket_id": str(ticket.id),
            },
            **self._get_headers(),
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    # --- Get messages ---

    def test_get_messages_with_identity(self):
        ticket = self._create_ticket()
        Comment.objects.create(
            team=self.team,
            scope="conversations_ticket",
            item_id=str(ticket.id),
            content="Test message",
            item_context={"author_type": "customer"},
        )

        response = self.client.get(
            f"/api/conversations/v1/widget/messages/{ticket.id}",
            {
                "identity_distinct_id": self.distinct_id,
                "identity_hash": self.identity_hash,
            },
            **self._get_headers(),
        )
        assert response.status_code == status.HTTP_200_OK
        assert len(response.json()["messages"]) == 1

    def test_get_messages_invalid_hash_no_session_returns_forbidden(self):
        ticket = self._create_ticket()
        response = self.client.get(
            f"/api/conversations/v1/widget/messages/{ticket.id}",
            {
                "identity_distinct_id": self.distinct_id,
                "identity_hash": "0" * 64,
            },
            **self._get_headers(),
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_get_messages_wrong_distinct_id_returns_forbidden(self):
        ticket = self._create_ticket(distinct_id="user_123")
        other_id = "user_456"
        other_hash = compute_identity_hash(other_id, self.secret)

        response = self.client.get(
            f"/api/conversations/v1/widget/messages/{ticket.id}",
            {
                "identity_distinct_id": other_id,
                "identity_hash": other_hash,
            },
            **self._get_headers(),
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    # --- Mark read ---

    def test_mark_read_with_identity(self):
        ticket = self._create_ticket()
        ticket.unread_customer_count = 3
        ticket.save()

        response = self.client.post(
            f"/api/conversations/v1/widget/messages/{ticket.id}/read",
            {
                "identity_distinct_id": self.distinct_id,
                "identity_hash": self.identity_hash,
            },
            **self._get_headers(),
        )
        assert response.status_code == status.HTTP_200_OK
        ticket.refresh_from_db()
        assert ticket.unread_customer_count == 0

    def test_mark_read_invalid_hash_no_session_returns_forbidden(self):
        ticket = self._create_ticket()
        response = self.client.post(
            f"/api/conversations/v1/widget/messages/{ticket.id}/read",
            {
                "identity_distinct_id": self.distinct_id,
                "identity_hash": "0" * 64,
            },
            **self._get_headers(),
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_mark_read_wrong_distinct_id_returns_forbidden(self):
        ticket = self._create_ticket(distinct_id="user_123")
        other_id = "user_456"
        other_hash = compute_identity_hash(other_id, self.secret)

        response = self.client.post(
            f"/api/conversations/v1/widget/messages/{ticket.id}/read",
            {
                "identity_distinct_id": other_id,
                "identity_hash": other_hash,
            },
            **self._get_headers(),
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN
