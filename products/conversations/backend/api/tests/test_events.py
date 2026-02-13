import uuid

from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from products.conversations.backend.events import (
    EVENT_SOURCE,
    capture_message_received,
    capture_message_sent,
    capture_ticket_assigned,
    capture_ticket_created,
    capture_ticket_priority_changed,
    capture_ticket_status_changed,
)
from products.conversations.backend.models import Ticket


class TestConversationEvents(BaseTest):
    def setUp(self):
        super().setUp()
        self.widget_session_id = str(uuid.uuid4())
        self.ticket = Ticket.objects.create_with_number(
            team=self.team,
            widget_session_id=self.widget_session_id,
            distinct_id="customer-123",
            channel_source="widget",
            status="new",
            priority="high",
            anonymous_traits={"name": "Test Customer", "email": "test@example.com"},
        )

    @patch("products.conversations.backend.events.capture_internal")
    def test_capture_ticket_created_uses_team_token(self, mock_capture):
        capture_ticket_created(self.ticket)

        mock_capture.assert_called_once()
        call_kwargs = mock_capture.call_args.kwargs
        assert call_kwargs["token"] == self.team.api_token
        assert call_kwargs["event_name"] == "$conversation_ticket_created"
        assert call_kwargs["event_source"] == EVENT_SOURCE
        assert call_kwargs["distinct_id"] == self.ticket.distinct_id
        assert call_kwargs["properties"]["ticket_id"] == str(self.ticket.id)
        assert call_kwargs["properties"]["customer_name"] == "Test Customer"
        assert call_kwargs["properties"]["customer_email"] == "test@example.com"

    @patch("products.conversations.backend.events.capture_internal")
    def test_capture_ticket_status_changed_uses_team_token(self, mock_capture):
        capture_ticket_status_changed(self.ticket, "new", "pending")

        mock_capture.assert_called_once()
        call_kwargs = mock_capture.call_args.kwargs
        assert call_kwargs["token"] == self.team.api_token
        assert call_kwargs["event_name"] == "$conversation_ticket_status_changed"
        assert call_kwargs["event_source"] == EVENT_SOURCE
        assert call_kwargs["distinct_id"] == self.ticket.distinct_id
        assert call_kwargs["properties"]["old_status"] == "new"
        assert call_kwargs["properties"]["new_status"] == "pending"

    @patch("products.conversations.backend.events.capture_internal")
    def test_capture_ticket_priority_changed_uses_team_token(self, mock_capture):
        capture_ticket_priority_changed(self.ticket, None, "high")

        mock_capture.assert_called_once()
        call_kwargs = mock_capture.call_args.kwargs
        assert call_kwargs["token"] == self.team.api_token
        assert call_kwargs["event_name"] == "$conversation_ticket_priority_changed"
        assert call_kwargs["event_source"] == EVENT_SOURCE
        assert call_kwargs["distinct_id"] == self.ticket.distinct_id
        assert call_kwargs["properties"]["old_priority"] is None
        assert call_kwargs["properties"]["new_priority"] == "high"

    @patch("products.conversations.backend.events.capture_internal")
    def test_capture_ticket_assigned_uses_team_token(self, mock_capture):
        capture_ticket_assigned(self.ticket, "user", "123")

        mock_capture.assert_called_once()
        call_kwargs = mock_capture.call_args.kwargs
        assert call_kwargs["token"] == self.team.api_token
        assert call_kwargs["event_name"] == "$conversation_ticket_assigned"
        assert call_kwargs["event_source"] == EVENT_SOURCE
        assert call_kwargs["distinct_id"] == self.ticket.distinct_id
        assert call_kwargs["properties"]["assignee_type"] == "user"
        assert call_kwargs["properties"]["assignee_id"] == "123"

    @patch("products.conversations.backend.events.capture_internal")
    def test_capture_message_sent_uses_team_token(self, mock_capture):
        capture_message_sent(self.ticket, "msg-123", "Hello customer", 42)

        mock_capture.assert_called_once()
        call_kwargs = mock_capture.call_args.kwargs
        assert call_kwargs["token"] == self.team.api_token
        assert call_kwargs["event_name"] == "$conversation_message_sent"
        assert call_kwargs["event_source"] == EVENT_SOURCE
        assert call_kwargs["distinct_id"] == self.ticket.distinct_id
        assert call_kwargs["properties"]["message_id"] == "msg-123"
        assert call_kwargs["properties"]["message_content"] == "Hello customer"
        assert call_kwargs["properties"]["author_type"] == "team"
        assert call_kwargs["properties"]["author_id"] == 42

    @patch("products.conversations.backend.events.capture_internal")
    def test_capture_message_received_uses_team_token(self, mock_capture):
        capture_message_received(self.ticket, "msg-456", "Hello support")

        mock_capture.assert_called_once()
        call_kwargs = mock_capture.call_args.kwargs
        assert call_kwargs["token"] == self.team.api_token
        assert call_kwargs["event_name"] == "$conversation_message_received"
        assert call_kwargs["event_source"] == EVENT_SOURCE
        assert call_kwargs["distinct_id"] == self.ticket.distinct_id
        assert call_kwargs["properties"]["message_id"] == "msg-456"
        assert call_kwargs["properties"]["message_content"] == "Hello support"
        assert call_kwargs["properties"]["author_type"] == "customer"
        assert call_kwargs["properties"]["customer_name"] == "Test Customer"
        assert call_kwargs["properties"]["customer_email"] == "test@example.com"

    @parameterized.expand(
        [
            ("capture_ticket_created", capture_ticket_created, "$conversation_ticket_created", []),
            (
                "capture_ticket_status_changed",
                capture_ticket_status_changed,
                "$conversation_ticket_status_changed",
                ["old", "new"],
            ),
            (
                "capture_ticket_priority_changed",
                capture_ticket_priority_changed,
                "$conversation_ticket_priority_changed",
                [None, "high"],
            ),
            ("capture_ticket_assigned", capture_ticket_assigned, "$conversation_ticket_assigned", ["user", "123"]),
            ("capture_message_sent", capture_message_sent, "$conversation_message_sent", ["msg-id", "content", 1]),
            (
                "capture_message_received",
                capture_message_received,
                "$conversation_message_received",
                ["msg-id", "content"],
            ),
        ]
    )
    @patch("products.conversations.backend.events.capture_internal")
    def test_all_events_include_base_properties(self, _name, capture_fn, expected_event, extra_args, mock_capture):
        capture_fn(self.ticket, *extra_args)

        mock_capture.assert_called_once()
        call_kwargs = mock_capture.call_args.kwargs
        assert call_kwargs["event_name"] == expected_event
        props = call_kwargs["properties"]
        assert props["ticket_id"] == str(self.ticket.id)
        assert props["ticket_number"] == self.ticket.ticket_number
        assert props["channel_source"] == self.ticket.channel_source
        assert props["status"] == self.ticket.status
        assert props["priority"] == self.ticket.priority

    @patch("products.conversations.backend.events.capture_internal")
    def test_message_content_truncated_to_1000_chars(self, mock_capture):
        long_content = "x" * 1500
        capture_message_sent(self.ticket, "msg-id", long_content, 1)

        call_kwargs = mock_capture.call_args.kwargs
        assert len(call_kwargs["properties"]["message_content"]) == 1000
