import time
import uuid

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.cache import cache
from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework import status
from rest_framework.test import APIClient

from posthog.models.comment import Comment
from posthog.rate_limit import WidgetTeamPollThrottle

from products.conversations.backend.api.serializers import WidgetMessageSerializer, WidgetTicketsQuerySerializer
from products.conversations.backend.models import SigningSecret, Ticket
from products.conversations.backend.models.constants import Channel, ChannelDetail, Status
from products.conversations.backend.services.identity import (
    IDENTITY_CLAIM_MAX_AGE_SECONDS,
    compute_identity_claim_hash,
    compute_identity_hash,
)


def _verification_counter(outcome: str, source: str) -> float:
    # Process-global, so callers compare deltas rather than absolute values.
    from prometheus_client import REGISTRY

    return (
        REGISTRY.get_sample_value("conversations_identity_verification_total", {"outcome": outcome, "source": source})
        or 0.0
    )


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
            headers={"x-conversations-token": "invalid_token"},
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

    def test_exhausted_poll_throttle_does_not_block_send(self):
        cache.clear()
        tickets_url = f"/api/conversations/v1/widget/tickets?widget_session_id={self.widget_session_id}"
        try:
            with patch.object(WidgetTeamPollThrottle, "rate", "1/minute"):
                self.assertEqual(self.client.get(tickets_url, **self._get_headers()).status_code, status.HTTP_200_OK)
                self.assertEqual(
                    self.client.get(tickets_url, **self._get_headers()).status_code, status.HTTP_429_TOO_MANY_REQUESTS
                )
                send = self.client.post(
                    "/api/conversations/v1/widget/message",
                    {
                        "message": "Hello, I need help!",
                        "widget_session_id": self.widget_session_id,
                        "distinct_id": self.distinct_id,
                    },
                    **self._get_headers(),
                )
            self.assertEqual(send.status_code, status.HTTP_200_OK)
        finally:
            cache.clear()

    def test_create_ticket_channel_detail_widget_enabled(self):
        self.team.conversations_settings = {**self.team.conversations_settings, "widget_enabled": True}
        self.team.save()
        response = self.client.post(
            "/api/conversations/v1/widget/message",
            {"message": "Hi", "widget_session_id": self.widget_session_id, "distinct_id": self.distinct_id},
            **self._get_headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ticket = Ticket.objects.get(id=response.json()["ticket_id"])
        self.assertEqual(ticket.channel_detail, ChannelDetail.WIDGET_EMBEDDED)

    def test_create_ticket_channel_detail_widget_disabled(self):
        self.team.conversations_settings = {**self.team.conversations_settings, "widget_enabled": False}
        self.team.save()
        response = self.client.post(
            "/api/conversations/v1/widget/message",
            {"message": "Hi", "widget_session_id": str(uuid.uuid4()), "distinct_id": "user-456"},
            **self._get_headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ticket = Ticket.objects.get(id=response.json()["ticket_id"])
        self.assertEqual(ticket.channel_detail, ChannelDetail.WIDGET_API)

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

    def test_list_tickets_limit_respected_after_default_page_cached(self):
        # Regression: the offset==0 cache key ignores limit, so a default-page
        # poll (limit=100) must not leak its full cached page to a ?limit=2 request.
        for _ in range(3):
            Ticket.objects.create_with_number(
                team=self.team,
                widget_session_id=self.widget_session_id,
                distinct_id=self.distinct_id,
                channel_source="widget",
                status=Status.NEW,
            )

        # Prime the cache with the default page size.
        default_page = self.client.get(
            f"/api/conversations/v1/widget/tickets?widget_session_id={self.widget_session_id}",
            **self._get_headers(),
        )
        self.assertEqual(default_page.status_code, status.HTTP_200_OK)
        self.assertEqual(len(default_page.json()["results"]), 3)

        limited = self.client.get(
            f"/api/conversations/v1/widget/tickets?widget_session_id={self.widget_session_id}&limit=2",
            **self._get_headers(),
        )
        self.assertEqual(limited.status_code, status.HTTP_200_OK)
        self.assertEqual(limited.json()["count"], 3)
        self.assertEqual(len(limited.json()["results"]), 2)

    def test_list_tickets_default_page_still_served_from_cache(self):
        # The widget polling path (offset=0, default limit) must still hit the
        # cache — the fix must not disable caching for the hot path.
        Ticket.objects.create_with_number(
            team=self.team,
            widget_session_id=self.widget_session_id,
            distinct_id=self.distinct_id,
            channel_source="widget",
            status=Status.NEW,
        )

        url = f"/api/conversations/v1/widget/tickets?widget_session_id={self.widget_session_id}"

        # First poll populates the cache, second poll is served from it.
        first = self.client.get(url, **self._get_headers())
        self.assertEqual(first.status_code, status.HTTP_200_OK)

        with patch("products.conversations.backend.api.widget.get_cached_tickets") as mock_get:
            mock_get.return_value = {"count": 99, "results": []}
            second = self.client.get(url, **self._get_headers())
            mock_get.assert_called_once()
            # Response comes straight from the cache, not the DB.
            self.assertEqual(second.json()["count"], 99)

    def test_list_tickets_custom_limit_never_reads_cache(self):
        # A custom limit must bypass the cache entirely (both read and write).
        Ticket.objects.create_with_number(
            team=self.team,
            widget_session_id=self.widget_session_id,
            distinct_id=self.distinct_id,
            channel_source="widget",
            status=Status.NEW,
        )

        with patch("products.conversations.backend.api.widget.get_cached_tickets") as mock_get:
            response = self.client.get(
                f"/api/conversations/v1/widget/tickets?widget_session_id={self.widget_session_id}&limit=2",
                **self._get_headers(),
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            mock_get.assert_not_called()

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
                "message": "x" * 10001,
                "widget_session_id": self.widget_session_id,
                "distinct_id": self.distinct_id,
            },
            **self._get_headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_long_current_url_is_truncated_not_rejected(self):
        long_url = "https://app.example.com/insights?q=" + "x" * 3000
        response = self.client.post(
            "/api/conversations/v1/widget/message",
            {
                "message": "Hello",
                "widget_session_id": self.widget_session_id,
                "distinct_id": self.distinct_id,
                "session_context": {"current_url": long_url},
            },
            **self._get_headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ticket = Ticket.objects.get(id=response.json()["ticket_id"])
        self.assertEqual(ticket.session_context["current_url"], long_url[:2000])


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

        cache.clear()
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
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 1)

    @parameterized.expand(
        [
            # Post-cutover state: with the legacy column gone, the signing secret alone has
            # to verify. Not reachable in production yet, so this locks in the end state.
            ("signing_secret_only", True, False),
            # A stale row (rotation sync missed) must fall back to the legacy token rather
            # than locking the team out.
            ("stale_signing_secret_falls_back_to_legacy", False, True),
        ]
    )
    def test_list_tickets_verifies_against_signing_secret(self, _name, row_matches_hash, has_legacy_token):
        SigningSecret.objects.for_team(self.team.id).create(
            team=self.team,
            secret=self.secret if row_matches_hash else "a_stale_secret",
        )
        self.team.secret_api_token = self.secret if has_legacy_token else None
        self.team.save()
        self._create_ticket()

        response = self.client.get(
            "/api/conversations/v1/widget/tickets",
            {
                "identity_distinct_id": self.distinct_id,
                "identity_hash": self.identity_hash,
            },
            **self._get_headers(),
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 1)

    def test_list_tickets_post_backfill_reports_the_signing_secret_as_the_source(self):
        # After the backfill both stores hold the same value, so the response is 200 either
        # way and only the counter shows which one matched. Without this, reordering the
        # candidates to put legacy first keeps the suite green while the drift metric —
        # what gates dropping the plaintext column — silently reports legacy forever.
        SigningSecret.objects.for_team(self.team.id).create(team=self.team, secret=self.secret)
        self._create_ticket()
        before_signing = _verification_counter("verified", "signing_secret")
        before_legacy = _verification_counter("verified", "legacy_token")

        response = self.client.get(
            "/api/conversations/v1/widget/tickets",
            {
                "identity_distinct_id": self.distinct_id,
                "identity_hash": self.identity_hash,
            },
            **self._get_headers(),
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(_verification_counter("verified", "signing_secret") - before_signing, 1.0)
        self.assertEqual(_verification_counter("verified", "legacy_token") - before_legacy, 0.0)

    def test_list_tickets_non_hex_identity_hash_is_rejected_not_a_server_error(self):
        # hmac.compare_digest raises TypeError on non-ASCII str, so a 64-character non-hex
        # hash used to reach it and surface as a 500 on a publicly reachable endpoint.
        response = self.client.get(
            "/api/conversations/v1/widget/tickets",
            {
                "identity_distinct_id": self.distinct_id,
                "identity_hash": "é" * 64,
            },
            **self._get_headers(),
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_list_tickets_stale_signing_secret_cannot_resurrect_revoked_key(self):
        # Rotating and then deleting the backup revokes the old key. If a rotation sync
        # didn't land, the signing secret row still holds that key — accepting it would
        # keep a revoked key signing identities indefinitely.
        SigningSecret.objects.for_team(self.team.id).create(team=self.team, secret=self.secret)
        self.team.secret_api_token = "rotated_new_secret"
        self.team.secret_api_token_backup = None
        self.team.save()
        self._create_ticket()

        response = self.client.get(
            "/api/conversations/v1/widget/tickets",
            {
                "identity_distinct_id": self.distinct_id,
                "identity_hash": self.identity_hash,
            },
            **self._get_headers(),
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

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
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_list_tickets_without_secret_api_token_is_indistinguishable_from_bad_hash(self):
        # The widget API is AllowAny, so the "no key configured" response must not reveal
        # config state to anonymous callers — it stays identical to a signature mismatch.
        self.team.secret_api_token = None
        self.team.save()

        response = self.client.get(
            "/api/conversations/v1/widget/tickets",
            {
                "identity_distinct_id": self.distinct_id,
                "identity_hash": self.identity_hash,
            },
            **self._get_headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.json()["error"], "Forbidden")

    def test_list_tickets_with_rotated_backup_token(self):
        # A hash signed with the old secret keeps verifying after rotation moves it to backup.
        old_secret = self.secret
        old_hash = compute_identity_hash(self.distinct_id, old_secret)
        self.team.secret_api_token = "rotated_new_secret"
        self.team.secret_api_token_backup = old_secret
        self.team.save()
        self._create_ticket()

        response = self.client.get(
            "/api/conversations/v1/widget/tickets",
            {
                "identity_distinct_id": self.distinct_id,
                "identity_hash": old_hash,
            },
            **self._get_headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 1)

    def test_list_tickets_missing_identity_fields_uses_session(self):
        self._create_ticket()
        response = self.client.get(
            "/api/conversations/v1/widget/tickets",
            {"widget_session_id": self.widget_session_id},
            **self._get_headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 1)

    # --- Widget session bridge ---

    def _identity_fields(self, *, with_session=False):
        fields = {"identity_distinct_id": self.distinct_id, "identity_hash": self.identity_hash}
        if with_session:
            fields["widget_session_id"] = self.widget_session_id
        return fields

    @parameterized.expand([("with_session", True, 1), ("without_session", False, 0)])
    def test_list_tickets_matches_only_a_widget_session_the_caller_sends(self, _name, with_session, expected_count):
        # A ticket started before sign-in keys on a distinct_id the verified person does not
        # own, so the browser's own session id is the only thing that keeps it in the list.
        self._create_ticket(distinct_id="anon_before_sign_in")

        response = self.client.get(
            "/api/conversations/v1/widget/tickets",
            self._identity_fields(with_session=with_session),
            **self._get_headers(),
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], expected_count)

    def test_list_tickets_ignores_a_widget_session_of_another_browser(self):
        self._create_ticket(distinct_id="anon_before_sign_in", widget_session_id=str(uuid.uuid4()))

        response = self.client.get(
            "/api/conversations/v1/widget/tickets",
            self._identity_fields(with_session=True),
            **self._get_headers(),
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 0)

    def test_read_messages_of_a_ticket_in_the_callers_own_widget_session(self):
        ticket = self._create_ticket(distinct_id="anon_before_sign_in")

        response = self.client.get(
            f"/api/conversations/v1/widget/messages/{ticket.id}",
            self._identity_fields(with_session=True),
            **self._get_headers(),
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_mark_read_of_a_ticket_in_the_callers_own_widget_session(self):
        ticket = self._create_ticket(distinct_id="anon_before_sign_in")
        ticket.unread_customer_count = 2
        ticket.save(update_fields=["unread_customer_count"])

        response = self.client.post(
            f"/api/conversations/v1/widget/messages/{ticket.id}/read",
            self._identity_fields(with_session=True),
            **self._get_headers(),
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ticket.refresh_from_db()
        self.assertEqual(ticket.unread_customer_count, 0)

    def test_reply_through_a_widget_session_does_not_rebind_the_ticket_identity(self):
        # Access here rests on possession of the session id alone. Rewriting the requester
        # would let anyone holding that id take the ticket over, so only a distinct_id match
        # may attest the ticket.
        ticket = self._create_ticket(distinct_id="anon_before_sign_in")
        ticket.identity_verified = False
        ticket.save(update_fields=["identity_verified"])

        response = self.client.post(
            "/api/conversations/v1/widget/message",
            {"message": "Any update?", "ticket_id": str(ticket.id), **self._identity_fields(with_session=True)},
            **self._get_headers(),
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ticket.refresh_from_db()
        self.assertEqual(ticket.distinct_id, "anon_before_sign_in")
        self.assertFalse(ticket.identity_verified)

    # --- Email claim bridge ---

    def _email_claim(self, email, *, expires_at=None):
        if expires_at is None:
            expires_at = int(time.time()) + IDENTITY_CLAIM_MAX_AGE_SECONDS
        return {
            "identity_email": email,
            "identity_hash_email": compute_identity_claim_hash(
                self.distinct_id,
                "email",
                email,
                self.secret,
                expires_at=expires_at,
            ),
            "identity_exp_email": expires_at,
        }

    def _create_email_ticket(
        self,
        email,
        identity_verified,
        *,
        channel_source=Channel.SLACK,
        zendesk_ticket_id=None,
        unread_customer_count=0,
    ):
        return Ticket.objects.create_with_number(
            team=self.team,
            widget_session_id=str(uuid.uuid4()),
            distinct_id=email,
            channel_source=channel_source,
            identity_verified=identity_verified,
            zendesk_ticket_id=zendesk_ticket_id,
            unread_customer_count=unread_customer_count,
        )

    def test_list_tickets_email_bridge_includes_verified_ticket(self):
        email = "person@example.com"
        self._create_email_ticket("Person@Example.com", identity_verified=True)
        response = self.client.get(
            "/api/conversations/v1/widget/tickets",
            {"identity_distinct_id": self.distinct_id, "identity_hash": self.identity_hash, **self._email_claim(email)},
            **self._get_headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 1)

    def test_list_tickets_email_bridge_includes_imported_ticket(self):
        email = "person@example.com"
        self._create_email_ticket(
            email,
            identity_verified=None,
            channel_source=Channel.EMAIL,
            zendesk_ticket_id=123,
        )
        response = self.client.get(
            "/api/conversations/v1/widget/tickets",
            {"identity_distinct_id": self.distinct_id, "identity_hash": self.identity_hash, **self._email_claim(email)},
            **self._get_headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 1)

    def test_list_tickets_email_bridge_ignores_unknown_legacy_widget_ticket(self):
        email = "person@example.com"
        self._create_email_ticket(email, identity_verified=None, channel_source=Channel.WIDGET)
        response = self.client.get(
            "/api/conversations/v1/widget/tickets",
            {"identity_distinct_id": self.distinct_id, "identity_hash": self.identity_hash, **self._email_claim(email)},
            **self._get_headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 0)

    def test_list_tickets_email_bridge_ignores_unverified_ticket(self):
        # identity_verified=False is attacker-controllable, so email must never bridge to it.
        email = "person@example.com"
        self._create_email_ticket(email, identity_verified=False)
        response = self.client.get(
            "/api/conversations/v1/widget/tickets",
            {"identity_distinct_id": self.distinct_id, "identity_hash": self.identity_hash, **self._email_claim(email)},
            **self._get_headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 0)

    def test_list_tickets_email_bridge_off_without_claim(self):
        email = "person@example.com"
        self._create_email_ticket(email, identity_verified=True)
        response = self.client.get(
            "/api/conversations/v1/widget/tickets",
            {"identity_distinct_id": self.distinct_id, "identity_hash": self.identity_hash},
            **self._get_headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 0)

    def test_list_tickets_tampered_email_claim_is_ignored(self):
        email = "person@example.com"
        self._create_email_ticket(email, identity_verified=True)
        email_claim = self._email_claim(email)
        email_claim["identity_hash_email"] = "0" * 64
        response = self.client.get(
            "/api/conversations/v1/widget/tickets",
            {
                "identity_distinct_id": self.distinct_id,
                "identity_hash": self.identity_hash,
                **email_claim,
            },
            **self._get_headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 0)

    def test_list_tickets_expired_email_claim_is_ignored(self):
        email = "person@example.com"
        self._create_email_ticket(email, identity_verified=True)
        response = self.client.get(
            "/api/conversations/v1/widget/tickets",
            {
                "identity_distinct_id": self.distinct_id,
                "identity_hash": self.identity_hash,
                **self._email_claim(email, expires_at=int(time.time()) - 1),
            },
            **self._get_headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 0)

    def test_list_tickets_legacy_email_claim_without_expiry_is_ignored(self):
        email = "person@example.com"
        self._create_email_ticket(email, identity_verified=True)
        response = self.client.get(
            "/api/conversations/v1/widget/tickets",
            {
                "identity_distinct_id": self.distinct_id,
                "identity_hash": self.identity_hash,
                "identity_email": email,
                "identity_hash_email": "0" * 64,
            },
            **self._get_headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 0)

    def test_list_tickets_modified_email_claim_expiry_is_ignored(self):
        email = "person@example.com"
        self._create_email_ticket(email, identity_verified=True)
        email_claim = self._email_claim(email)
        email_claim["identity_exp_email"] += 1
        response = self.client.get(
            "/api/conversations/v1/widget/tickets",
            {
                "identity_distinct_id": self.distinct_id,
                "identity_hash": self.identity_hash,
                **email_claim,
            },
            **self._get_headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 0)

    def test_list_tickets_email_claim_bound_to_other_distinct_id_is_ignored(self):
        # A claim signed for a different base identity must not bridge under this viewer.
        email = "person@example.com"
        self._create_email_ticket(email, identity_verified=True)
        email_claim = self._email_claim(email)
        email_claim["identity_hash_email"] = compute_identity_claim_hash(
            "someone_else",
            "email",
            email,
            self.secret,
            expires_at=email_claim["identity_exp_email"],
        )
        response = self.client.get(
            "/api/conversations/v1/widget/tickets",
            {
                "identity_distinct_id": self.distinct_id,
                "identity_hash": self.identity_hash,
                **email_claim,
            },
            **self._get_headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 0)

    def test_list_tickets_cache_does_not_leak_bridged_tickets_without_claim(self):
        email = "person@example.com"
        self._create_ticket()
        self._create_email_ticket(email, identity_verified=True)

        claimed_response = self.client.get(
            "/api/conversations/v1/widget/tickets",
            {"identity_distinct_id": self.distinct_id, "identity_hash": self.identity_hash, **self._email_claim(email)},
            **self._get_headers(),
        )
        unclaimed_response = self.client.get(
            "/api/conversations/v1/widget/tickets",
            {"identity_distinct_id": self.distinct_id, "identity_hash": self.identity_hash},
            **self._get_headers(),
        )

        self.assertEqual(claimed_response.json()["count"], 2)
        self.assertEqual(unclaimed_response.json()["count"], 1)

    def test_list_tickets_cache_does_not_hide_bridge_after_unclaimed_request(self):
        email = "person@example.com"
        self._create_ticket()
        self._create_email_ticket(email, identity_verified=True)

        unclaimed_response = self.client.get(
            "/api/conversations/v1/widget/tickets",
            {"identity_distinct_id": self.distinct_id, "identity_hash": self.identity_hash},
            **self._get_headers(),
        )
        claimed_response = self.client.get(
            "/api/conversations/v1/widget/tickets",
            {"identity_distinct_id": self.distinct_id, "identity_hash": self.identity_hash, **self._email_claim(email)},
            **self._get_headers(),
        )

        self.assertEqual(unclaimed_response.json()["count"], 1)
        self.assertEqual(claimed_response.json()["count"], 2)

    @parameterized.expand([("direct_identity", False), ("email_claim", True)])
    def test_new_message_invalidates_identity_ticket_cache(self, _name, use_email_claim):
        email = "person@example.com"
        ticket = self._create_email_ticket(email, identity_verified=True) if use_email_claim else self._create_ticket()
        query = {
            "identity_distinct_id": self.distinct_id,
            "identity_hash": self.identity_hash,
        }
        if use_email_claim:
            query.update(self._email_claim(email))

        initial_response = self.client.get(
            "/api/conversations/v1/widget/tickets",
            query,
            **self._get_headers(),
        )
        self.assertEqual(initial_response.status_code, status.HTTP_200_OK)
        self.assertEqual(initial_response.json()["results"][0]["unread_count"], 0)

        with self.captureOnCommitCallbacks(execute=True):
            Comment.objects.create(
                team=self.team,
                scope="conversations_ticket",
                item_id=str(ticket.id),
                content="Agent reply",
                created_by=self.user,
                item_context={"author_type": "team", "is_private": False},
            )

        updated_response = self.client.get(
            "/api/conversations/v1/widget/tickets",
            query,
            **self._get_headers(),
        )
        self.assertEqual(updated_response.status_code, status.HTTP_200_OK)
        self.assertEqual(updated_response.json()["results"][0]["unread_count"], 1)
        self.assertEqual(updated_response.json()["results"][0]["last_message"], "Agent reply")

    def test_get_messages_email_bridge_allows_verified_ticket(self):
        email = "person@example.com"
        ticket = self._create_email_ticket("Person@Example.com", identity_verified=True)
        response = self.client.get(
            f"/api/conversations/v1/widget/messages/{ticket.id}",
            {"identity_distinct_id": self.distinct_id, "identity_hash": self.identity_hash, **self._email_claim(email)},
            **self._get_headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_get_messages_email_bridge_denies_unverified_ticket(self):
        email = "person@example.com"
        ticket = self._create_email_ticket(email, identity_verified=False)
        response = self.client.get(
            f"/api/conversations/v1/widget/messages/{ticket.id}",
            {"identity_distinct_id": self.distinct_id, "identity_hash": self.identity_hash, **self._email_claim(email)},
            **self._get_headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_email_bridge_list_and_detail_reject_whitespace_padded_ticket_identity(self):
        email = "person@example.com"
        ticket = self._create_email_ticket(f" {email} ", identity_verified=True)

        list_response = self.client.get(
            "/api/conversations/v1/widget/tickets",
            {"identity_distinct_id": self.distinct_id, "identity_hash": self.identity_hash, **self._email_claim(email)},
            **self._get_headers(),
        )
        detail_response = self.client.get(
            f"/api/conversations/v1/widget/messages/{ticket.id}",
            {"identity_distinct_id": self.distinct_id, "identity_hash": self.identity_hash, **self._email_claim(email)},
            **self._get_headers(),
        )

        self.assertEqual(list_response.json()["count"], 0)
        self.assertEqual(detail_response.status_code, status.HTTP_403_FORBIDDEN)

    @parameterized.expand(
        [
            ("zendesk", None, Channel.EMAIL, 123),
            ("slack", True, Channel.SLACK, None),
        ]
    )
    def test_send_message_to_bridged_ticket_preserves_channel_identity(
        self, _name, identity_verified, channel_source, zendesk_ticket_id
    ):
        email = "person@example.com"
        ticket = self._create_email_ticket(
            email,
            identity_verified=identity_verified,
            channel_source=channel_source,
            zendesk_ticket_id=zendesk_ticket_id,
        )
        response = self.client.post(
            "/api/conversations/v1/widget/message",
            {
                "identity_distinct_id": self.distinct_id,
                "identity_hash": self.identity_hash,
                **self._email_claim(email),
                "message": "Follow-up",
                "ticket_id": str(ticket.id),
            },
            **self._get_headers(),
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ticket.refresh_from_db()
        self.assertEqual(ticket.distinct_id, email)
        self.assertEqual(ticket.identity_verified, identity_verified)

    def test_mark_read_email_bridge_allows_verified_ticket(self):
        email = "person@example.com"
        ticket = self._create_email_ticket(email, identity_verified=True, unread_customer_count=1)

        response = self.client.post(
            f"/api/conversations/v1/widget/messages/{ticket.id}/read",
            {"identity_distinct_id": self.distinct_id, "identity_hash": self.identity_hash, **self._email_claim(email)},
            format="json",
            **self._get_headers(),
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ticket.refresh_from_db()
        self.assertEqual(ticket.unread_customer_count, 0)

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
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 1)

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
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ticket = Ticket.objects.get(id=response.json()["ticket_id"])
        self.assertEqual(ticket.distinct_id, self.distinct_id)
        self.assertTrue(ticket.identity_verified)

    def test_anonymous_message_creates_unverified_ticket(self):
        # A widget_session_id-only (no HMAC) request is not server-attested.
        response = self.client.post(
            "/api/conversations/v1/widget/message",
            {
                "widget_session_id": self.widget_session_id,
                "distinct_id": self.distinct_id,
                "message": "Anonymous hello",
            },
            **self._get_headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ticket = Ticket.objects.get(id=response.json()["ticket_id"])
        self.assertFalse(ticket.identity_verified)

    def test_verified_message_promotes_anonymous_ticket(self):
        # An existing anonymous ticket becomes verified once an HMAC-verified
        # message with the matching distinct_id lands on it.
        ticket = self._create_ticket()
        self.assertFalse(ticket.identity_verified)

        response = self.client.post(
            "/api/conversations/v1/widget/message",
            {
                "identity_distinct_id": self.distinct_id,
                "identity_hash": self.identity_hash,
                "message": "Now verified",
                "ticket_id": str(ticket.id),
            },
            **self._get_headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ticket.refresh_from_db()
        self.assertTrue(ticket.identity_verified)

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
        self.assertEqual(response.status_code, status.HTTP_200_OK)

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
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

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
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

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
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["messages"]), 1)

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
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

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
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    # --- Mark read ---

    def test_mark_read_with_identity(self):
        ticket = self._create_ticket()
        ticket.unread_customer_count = 3
        ticket.save()
        identity = {
            "identity_distinct_id": self.distinct_id,
            "identity_hash": self.identity_hash,
        }

        cached_response = self.client.get(
            "/api/conversations/v1/widget/tickets",
            identity,
            **self._get_headers(),
        )
        self.assertEqual(cached_response.json()["results"][0]["unread_count"], 3)

        response = self.client.post(
            f"/api/conversations/v1/widget/messages/{ticket.id}/read",
            identity,
            **self._get_headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ticket.refresh_from_db()
        self.assertEqual(ticket.unread_customer_count, 0)
        updated_response = self.client.get(
            "/api/conversations/v1/widget/tickets",
            identity,
            **self._get_headers(),
        )
        self.assertEqual(updated_response.json()["results"][0]["unread_count"], 0)

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
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

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
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class TestWidgetAuthSerializer(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "email_without_hash",
                {
                    "identity_distinct_id": "user_123",
                    "identity_hash": "a" * 64,
                    "identity_email": "person@example.com",
                    "identity_exp_email": int(time.time()) + IDENTITY_CLAIM_MAX_AGE_SECONDS,
                },
            ),
            (
                "hash_without_email",
                {
                    "identity_distinct_id": "user_123",
                    "identity_hash": "a" * 64,
                    "identity_hash_email": "b" * 64,
                    "identity_exp_email": int(time.time()) + IDENTITY_CLAIM_MAX_AGE_SECONDS,
                },
            ),
            (
                "claim_without_base_identity",
                {
                    "widget_session_id": str(uuid.uuid4()),
                    "identity_email": "person@example.com",
                    "identity_hash_email": "b" * 64,
                    "identity_exp_email": int(time.time()) + IDENTITY_CLAIM_MAX_AGE_SECONDS,
                },
            ),
        ]
    )
    def test_email_claim_requires_complete_base_and_claim_triplet(self, _name, payload):
        serializer = WidgetTicketsQuerySerializer(data=payload)

        self.assertFalse(serializer.is_valid())
        self.assertIn("non_field_errors", serializer.errors)

    def test_legacy_email_claim_pair_is_accepted(self):
        serializer = WidgetTicketsQuerySerializer(
            data={
                "identity_distinct_id": "user_123",
                "identity_hash": "a" * 64,
                "identity_email": "person@example.com",
                "identity_hash_email": "b" * 64,
            }
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)


class TestWidgetContextSanitization(SimpleTestCase):
    def _serializer(self, **overrides):
        return WidgetMessageSerializer(
            data={
                "widget_session_id": str(uuid.uuid4()),
                "distinct_id": "user-123",
                "message": "Hello",
                **overrides,
            }
        )

    def _validated(self, **overrides):
        serializer = self._serializer(**overrides)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        return serializer.validated_data

    @parameterized.expand(
        [
            ("session_context", "current_url", 2000),
            ("traits", "name", 500),
        ]
    )
    def test_oversized_value_is_truncated(self, field, key, max_length):
        value = "x" * (max_length + 500)

        validated = self._validated(**{field: {key: value}})

        self.assertEqual(validated[field][key], value[:max_length])

    @parameterized.expand(
        [
            ("session_context", 20, 100),
            ("traits", 50, 200),
        ]
    )
    def test_long_keys_and_excess_entries_are_dropped(self, field, max_entries, max_key_length):
        long_key = "k" * (max_key_length + 1)
        payload = {long_key: "value", **{f"key_{i}": "value" for i in range(max_entries + 5)}}

        validated = self._validated(**{field: payload})

        self.assertNotIn(long_key, validated[field])
        self.assertEqual(len(validated[field]), max_entries)

    @parameterized.expand(
        [
            (
                "session_context",
                {"tab_index": 3, "is_replay": True, "referrer": None},
                {"tab_index": 3, "is_replay": True, "referrer": None},
            ),
            (
                "traits",
                {"plan_seats": 3, "is_admin": True, "email": None},
                {"plan_seats": "3", "is_admin": "True", "email": None},
            ),
        ]
    )
    def test_non_string_values_are_coerced_per_field(self, field, payload, expected):
        validated = self._validated(**{field: payload})

        self.assertEqual(validated[field], expected)

    @parameterized.expand(
        [
            ("session_context", "not-a-dict"),
            ("session_context", None),
            ("traits", "not-a-dict"),
            ("traits", None),
        ]
    )
    def test_structurally_malformed_context_is_still_rejected(self, field, value):
        serializer = self._serializer(**{field: value})

        self.assertFalse(serializer.is_valid())
        self.assertIn(field, serializer.errors)
