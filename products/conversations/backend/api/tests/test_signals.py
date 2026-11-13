import uuid
from collections.abc import Mapping
from contextlib import nullcontext
from typing import Any, cast

import pytest
from posthog.test.base import APIBaseTest, BaseTest
from unittest.mock import ANY, MagicMock, patch

from django.db import transaction

from celery.exceptions import Retry
from parameterized import parameterized
from rest_framework import status
from rest_framework.test import APIClient

from posthog.api.capture import CaptureInternalResult
from posthog.models.comment import Comment
from posthog.models.tag import Tag
from posthog.models.tagged_item import TaggedItem
from posthog.models.tagged_item_registry import content_type_id_for_legacy_field
from posthog.models.team import Team

from products.conversations.backend.ai.human_outcome import record_human_outcome
from products.conversations.backend.api.internal import CONVERSATIONS_TICKETS_PURPOSE
from products.conversations.backend.events import build_ticket_tag_added_event
from products.conversations.backend.models import (
    ConversationDeliveryPart,
    EmailChannel,
    EmailOutboxMessage,
    TeamConversationsSlackConfig,
    Ticket,
)
from products.conversations.backend.models.constants import Channel, Status
from products.conversations.backend.tasks.ticket_events import emit_ticket_tag_added


# Patch on_commit to execute immediately in tests
def immediate_on_commit(func):
    func()


@patch.object(transaction, "on_commit", side_effect=immediate_on_commit)
class TestTicketMessageSignals(BaseTest):
    """Tests for signal handlers that maintain denormalized ticket stats."""

    def setUp(self):
        super().setUp()
        self.widget_session_id = str(uuid.uuid4())
        self.ticket = Ticket.objects.create_with_number(
            team=self.team,
            widget_session_id=self.widget_session_id,
            distinct_id="user-123",
            channel_source="widget",
        )

    def _create_customer_message(self, content: str = "Hello") -> Comment:
        return Comment.objects.create(
            team=self.team,
            scope="conversations_ticket",
            item_id=str(self.ticket.id),
            content=content,
            item_context={"author_type": "customer", "is_private": False},
        )

    def _create_team_message(self, content: str = "Hi there", is_private: bool = False) -> Comment:
        return Comment.objects.create(
            team=self.team,
            scope="conversations_ticket",
            item_id=str(self.ticket.id),
            content=content,
            created_by=self.user,
            item_context={"author_type": "team", "is_private": is_private},
        )

    def _create_ai_message(
        self, content: str, *, is_private: bool = True, deleted: bool = False, item_context: dict | None = None
    ) -> Comment:
        return Comment.objects.create(
            team=self.team,
            scope="conversations_ticket",
            item_id=str(self.ticket.id),
            content=content,
            item_context={"author_type": "AI", "is_private": is_private, **(item_context or {})},
            deleted=deleted,
        )

    def test_customer_message_updates_stats(self, mock_on_commit):
        comment = self._create_customer_message("Hello from customer")

        self.ticket.refresh_from_db()
        assert self.ticket.message_count == 1
        assert self.ticket.last_message_at == comment.created_at
        assert self.ticket.last_message_text == "Hello from customer"
        assert self.ticket.updated_at == comment.created_at
        assert self.ticket.unread_customer_count == 0  # Customer messages don't increment this

    @parameterized.expand(
        [
            ("written_by_the_channel", False, True),
            ("written_by_a_posthog_user", True, False),
        ]
    )
    @patch("products.conversations.backend.events.capture_internal")
    def test_customer_message_event_checks_the_message_author(
        self, _name, has_created_by, expected, mock_capture, mock_on_commit
    ):
        Ticket.objects.filter(id=self.ticket.id).update(
            identity_verified=True,
            distinct_id="customer@example.com",
            anonymous_traits={"email": "customer@example.com"},
        )

        Comment.objects.create(
            team=self.team,
            scope="conversations_ticket",
            item_id=str(self.ticket.id),
            content="Hello",
            created_by=self.user if has_created_by else None,
            item_context={
                "author_type": "customer",
                "distinct_id": "customer@example.com",
                "distinct_id_verified": True,
                "is_private": False,
            },
        )

        assert mock_capture.call_args.kwargs["properties"]["customer_email_verified"] is expected

    @patch("products.conversations.backend.signals.report_team_action")
    @patch("products.conversations.backend.signals.capture_message_received")
    @patch("products.conversations.backend.signals.capture_message_sent")
    def test_public_workflow_message_counts_without_emitting_a_trigger_event(
        self, mock_sent, mock_received, mock_report_team, mock_on_commit
    ):
        Comment.objects.create(
            team=self.team,
            scope="conversations_ticket",
            item_id=str(self.ticket.id),
            content="Automated reply",
            item_context={"author_type": "workflow", "is_private": False},
        )

        self.ticket.refresh_from_db()
        assert self.ticket.message_count == 1
        assert self.ticket.last_message_text == "Automated reply"
        assert self.ticket.unread_customer_count == 1
        mock_sent.assert_not_called()
        mock_received.assert_not_called()
        mock_report_team.assert_called_once_with(
            self.team,
            "support message sent",
            {"channel_source": self.ticket.channel_source},
        )

    def test_team_message_updates_stats_and_unread(self, mock_on_commit):
        comment = self._create_team_message("Response from team")

        self.ticket.refresh_from_db()
        assert self.ticket.message_count == 1
        assert self.ticket.last_message_at == comment.created_at
        assert self.ticket.last_message_text == "Response from team"
        assert self.ticket.updated_at == comment.created_at
        assert self.ticket.unread_customer_count == 1  # Team messages increment this

    def test_first_public_human_reply_records_human_outcome(self, mock_on_commit):
        draft = "Add the snippet to the head of every page."
        self._create_ai_message(draft)
        self._create_team_message(draft)

        self.ticket.refresh_from_db()
        assert self.ticket.ai_triage["human_outcome"] == "used"

    def test_automated_update_does_not_replace_draft_for_human_outcome(self, mock_on_commit):
        draft = "Add the snippet to the head of every page."
        self._create_ai_message(draft)
        self._create_ai_message("Pull request update", item_context={"automated_update_key": "pr-123"})
        self._create_team_message(draft)

        self.ticket.refresh_from_db()
        assert self.ticket.ai_triage["human_outcome"] == "used"

    def test_used_draft_then_edited_send_upgrades_human_outcome(self, mock_on_commit):
        draft = "Add the snippet to the head of every page, then reload to send a pageview."
        ai_draft = self._create_ai_message(draft)
        record_human_outcome(
            team_id=self.team.id,
            ticket_id=str(self.ticket.id),
            draft_message_id=str(ai_draft.id),
            outcome="used",
        )
        self._create_team_message("Drop the recorder snippet on checkout only, then hard-refresh to send a pageview.")

        self.ticket.refresh_from_db()
        assert self.ticket.ai_triage["human_outcome"] == "edited"

    def test_used_question_sent_unchanged_stays_used(self, mock_on_commit):
        question = "Which SDK are you using?"
        ai_draft = self._create_ai_message(
            f"Suggested question for the customer:\n- {question}\n\nChecked the docs.\n\nStill unknown:\n- SDK version",
            item_context={"persist_as": "clarification", "clarifying_questions": [question]},
        )
        record_human_outcome(
            team_id=self.team.id,
            ticket_id=str(self.ticket.id),
            draft_message_id=str(ai_draft.id),
            outcome="used",
        )
        self._create_team_message(question)

        self.ticket.refresh_from_db()
        assert self.ticket.ai_triage["human_outcome"] == "used"

    def test_used_question_then_unrelated_send_is_ignored(self, mock_on_commit):
        question = "Which SDK are you using?"
        ai_draft = self._create_ai_message(
            f"Suggested question for the customer:\n- {question}",
            item_context={"persist_as": "clarification", "clarifying_questions": [question]},
        )
        record_human_outcome(
            team_id=self.team.id,
            ticket_id=str(self.ticket.id),
            draft_message_id=str(ai_draft.id),
            outcome="used",
        )
        self._create_team_message("We migrated this org to a new plan yesterday.")

        self.ticket.refresh_from_db()
        assert self.ticket.ai_triage["human_outcome"] == "ignored"

    def test_second_public_human_reply_does_not_overwrite_human_outcome(self, mock_on_commit):
        draft = "Add the snippet to the head of every page."
        self._create_ai_message(draft)
        self._create_team_message(draft)
        self._create_team_message("We migrated this org to a new plan yesterday.")

        self.ticket.refresh_from_db()
        assert self.ticket.ai_triage["human_outcome"] == "used"

    def test_private_human_note_does_not_record_human_outcome(self, mock_on_commit):
        self._create_ai_message("Add the snippet to the head of every page.")
        self._create_team_message("Add the snippet to the head of every page.", is_private=True)

        self.ticket.refresh_from_db()
        assert "human_outcome" not in (self.ticket.ai_triage or {})

    def test_human_reply_without_ai_note_does_not_record_human_outcome(self, mock_on_commit):
        self._create_team_message("Add the snippet to the head of every page.")

        self.ticket.refresh_from_db()
        assert "human_outcome" not in (self.ticket.ai_triage or {})

    def test_public_ai_reply_is_not_treated_as_a_draft(self, mock_on_commit):
        draft = "Add the snippet to the head of every page."
        self._create_ai_message(draft)
        self._create_ai_message("Totally different automated billing answer.", is_private=False)
        self._create_team_message(draft)

        self.ticket.refresh_from_db()
        assert self.ticket.ai_triage["human_outcome"] == "used"

    def test_deleted_ai_note_is_not_the_similarity_target(self, mock_on_commit):
        draft = "Add the snippet to the head of every page."
        self._create_ai_message(draft)
        self._create_ai_message("A deleted unrelated draft.", deleted=True)
        self._create_team_message(draft)

        self.ticket.refresh_from_db()
        assert self.ticket.ai_triage["human_outcome"] == "used"

    def test_human_reply_before_ai_note_does_not_block_later_outcome(self, mock_on_commit):
        draft = "Add the snippet to the head of every page."
        self._create_team_message("Looking into this.")
        self._create_ai_message(draft)
        self._create_team_message(draft)

        self.ticket.refresh_from_db()
        assert self.ticket.ai_triage["human_outcome"] == "used"

    def test_human_reply_clears_awaiting_clarification(self, mock_on_commit):
        Ticket.objects.filter(id=self.ticket.id).update(
            ai_triage={"status": "awaiting_clarification", "result": "clarified"}
        )
        self._create_team_message("Taking this.")
        self.ticket.refresh_from_db()
        assert self.ticket.ai_triage["status"] == "done"
        assert self.ticket.ai_triage["result"] == "clarified"

    def test_private_human_note_clears_awaiting_clarification(self, mock_on_commit):
        Ticket.objects.filter(id=self.ticket.id).update(
            ai_triage={"status": "awaiting_clarification", "result": "clarified"}
        )
        self._create_team_message("Taking this.", is_private=True)
        self.ticket.refresh_from_db()
        assert self.ticket.ai_triage["status"] == "done"

    def test_customer_reply_does_not_clear_awaiting_clarification(self, mock_on_commit):
        Ticket.objects.filter(id=self.ticket.id).update(
            ai_triage={"status": "awaiting_clarification", "result": "clarified"}
        )
        self._create_customer_message("We're on the JavaScript SDK.")
        self.ticket.refresh_from_db()
        assert self.ticket.ai_triage["status"] == "awaiting_clarification"

    @patch("products.conversations.backend.signals.capture_message_sent")
    @patch(
        "products.conversations.backend.signals.maybe_record_human_outcome",
        side_effect=RuntimeError("boom"),
    )
    def test_human_outcome_failure_does_not_block_message_analytics(self, _mock_record, mock_sent, mock_on_commit):
        self._create_team_message("Thanks")
        mock_sent.assert_called_once()

    def test_multiple_messages_accumulate(self, mock_on_commit):
        self._create_customer_message("First")
        self._create_team_message("Second")
        last = self._create_customer_message("Third")

        self.ticket.refresh_from_db()
        assert self.ticket.message_count == 3
        assert self.ticket.last_message_at == last.created_at
        assert self.ticket.updated_at == last.created_at
        assert self.ticket.last_message_text == "Third"
        assert self.ticket.unread_customer_count == 1  # Only 1 team message

    def test_long_message_truncated_to_500_chars(self, mock_on_commit):
        long_content = "x" * 600
        self._create_customer_message(long_content)

        self.ticket.refresh_from_db()
        assert len(self.ticket.last_message_text) == 500
        assert self.ticket.last_message_text == "x" * 500

    def test_soft_delete_decrements_count(self, mock_on_commit):
        comment = self._create_customer_message("To be deleted")
        self.ticket.refresh_from_db()
        assert self.ticket.message_count == 1

        comment.deleted = True
        comment.save()

        self.ticket.refresh_from_db()
        assert self.ticket.message_count == 0

    def test_soft_delete_recalculates_last_message(self, mock_on_commit):
        first = self._create_customer_message("First message")
        second = self._create_customer_message("Second message")

        self.ticket.refresh_from_db()
        assert self.ticket.last_message_text == "Second message"

        second.deleted = True
        second.save()

        self.ticket.refresh_from_db()
        assert self.ticket.message_count == 1
        assert self.ticket.last_message_at == first.created_at
        assert self.ticket.last_message_text == "First message"

    def test_soft_delete_last_message_clears_last_message_fields(self, mock_on_commit):
        comment = self._create_customer_message("Only message")
        self.ticket.refresh_from_db()
        assert self.ticket.last_message_text == "Only message"

        comment.deleted = True
        comment.save()

        self.ticket.refresh_from_db()
        assert self.ticket.message_count == 0
        assert self.ticket.last_message_at is None
        assert self.ticket.last_message_text is None

    def test_soft_delete_team_message_decrements_unread(self, mock_on_commit):
        comment = self._create_team_message("Team response")
        self.ticket.refresh_from_db()
        assert self.ticket.unread_customer_count == 1

        comment.deleted = True
        comment.save()

        self.ticket.refresh_from_db()
        assert self.ticket.unread_customer_count == 0

    def test_soft_delete_prevents_negative_counts(self, mock_on_commit):
        # Manually set count to 0 to simulate race condition / data inconsistency
        Ticket.objects.filter(id=self.ticket.id).update(message_count=0, unread_customer_count=0)

        comment = self._create_team_message("Message")
        # Reset counts again before delete to simulate race
        Ticket.objects.filter(id=self.ticket.id).update(message_count=0, unread_customer_count=0)

        comment.deleted = True
        comment.save()

        self.ticket.refresh_from_db()
        assert self.ticket.message_count == 0  # Not -1
        assert self.ticket.unread_customer_count == 0  # Not -1

    def test_non_conversations_comment_ignored(self, mock_on_commit):
        # Comment for a different scope (e.g., recordings)
        Comment.objects.create(
            team=self.team,
            scope="recordings",
            item_id="some-recording-id",
            content="Recording comment",
        )

        self.ticket.refresh_from_db()
        assert self.ticket.message_count == 0  # Unchanged

    def test_comment_without_item_id_ignored(self, mock_on_commit):
        Comment.objects.create(
            team=self.team,
            scope="conversations_ticket",
            item_id=None,
            content="Orphan comment",
        )

        self.ticket.refresh_from_db()
        assert self.ticket.message_count == 0  # Unchanged

    def test_private_message_does_not_update_denormalized_stats(self, mock_on_commit):
        """Private messages should not update message_count, last_message_at, or last_message_text."""
        self._create_team_message("Private note", is_private=True)

        self.ticket.refresh_from_db()
        assert self.ticket.message_count == 0  # Not incremented
        assert self.ticket.last_message_at is None  # Not updated
        assert self.ticket.last_message_text is None  # Not updated
        assert self.ticket.unread_customer_count == 0  # Not incremented

    def test_private_message_does_not_affect_existing_last_message(self, mock_on_commit):
        """A private message sent after a public message should not change last_message_text."""
        public_msg = self._create_customer_message("Public message")

        self.ticket.refresh_from_db()
        assert self.ticket.message_count == 1
        assert self.ticket.last_message_text == "Public message"
        assert self.ticket.last_message_at == public_msg.created_at
        assert self.ticket.updated_at == public_msg.created_at

        # Now send a private message - should not change last_message_* or updated_at
        self._create_team_message("Private note for team only", is_private=True)

        self.ticket.refresh_from_db()
        assert self.ticket.message_count == 1  # Still 1
        assert self.ticket.last_message_text == "Public message"  # Unchanged
        assert self.ticket.last_message_at == public_msg.created_at  # Unchanged
        assert self.ticket.updated_at == public_msg.created_at  # Unchanged

    @patch("products.conversations.backend.events.capture_internal")
    def test_private_team_note_emits_private_message_sent_event(self, mock_capture, mock_on_commit):
        self._create_team_message("Private note", is_private=True)

        self.ticket.refresh_from_db()
        assert self.ticket.message_count == 0
        mock_capture.assert_called_once()
        call_kwargs = mock_capture.call_args.kwargs
        assert call_kwargs["event_name"] == "$conversation_private_message_sent"
        assert call_kwargs["properties"]["actor_id"] == self.user.id
        # The note body must never reach the event stream: analytics events are
        # team-scoped and bypass ticket-level access controls
        assert "message_content" not in call_kwargs["properties"]
        assert "Private note" not in str(call_kwargs["properties"])

    @patch("products.conversations.backend.events.capture_internal")
    def test_private_ai_message_emits_no_event(self, mock_capture, mock_on_commit):
        # Private AI messages have no human actor; emitting them would fire workflows with an empty actor
        Comment.objects.create(
            team=self.team,
            scope="conversations_ticket",
            item_id=str(self.ticket.id),
            content="AI draft suggestion",
            item_context={"author_type": "AI", "is_private": True},
        )

        mock_capture.assert_not_called()

    def test_soft_delete_private_message_does_not_decrement_count(self, mock_on_commit):
        """Deleting a private message should not decrement message_count (since it wasn't counted)."""
        self._create_customer_message("Public message")
        private_msg = self._create_team_message("Private note", is_private=True)

        self.ticket.refresh_from_db()
        assert self.ticket.message_count == 1  # Only the public message

        private_msg.deleted = True
        private_msg.save()

        self.ticket.refresh_from_db()
        assert self.ticket.message_count == 1  # Still 1, not decremented

    def test_soft_delete_recalculates_last_message_from_non_private_only(self, mock_on_commit):
        """When recalculating last_message after delete, only consider non-private messages."""
        first_public = self._create_customer_message("First public")
        self._create_team_message("Private note", is_private=True)
        second_public = self._create_customer_message("Second public")

        self.ticket.refresh_from_db()
        assert self.ticket.message_count == 2  # Only public messages counted
        assert self.ticket.last_message_text == "Second public"

        # Delete the second public message
        second_public.deleted = True
        second_public.save()

        self.ticket.refresh_from_db()
        assert self.ticket.message_count == 1
        # Should fall back to first_public, not the private message
        assert self.ticket.last_message_text == "First public"
        assert self.ticket.last_message_at == first_public.created_at

    @patch("products.conversations.backend.signals.wake_delivery_part")
    def test_slack_ticket_team_message_enqueues_slack_reply(self, mock_wake, mock_on_commit):
        self.team.conversations_settings = {"slack_enabled": True}
        self.team.save()
        TeamConversationsSlackConfig.objects.update_or_create(
            team=self.team,
            defaults={"slack_team_id": "T123", "slack_bot_token": "xoxb-test"},
        )
        slack_ticket = Ticket.objects.create_with_number(
            team=self.team,
            widget_session_id=self.widget_session_id,
            distinct_id="slack-user-1",
            channel_source=Channel.SLACK,
            slack_channel_id="C123",
            slack_thread_ts="1700000000.000100",
        )

        Comment.objects.create(
            team=self.team,
            scope="conversations_ticket",
            item_id=str(slack_ticket.id),
            content="Support reply",
            created_by=self.user,
            item_context={"author_type": "team", "is_private": False},
        )

        mock_wake.assert_called_once()
        part = ConversationDeliveryPart.objects.unscoped().get()
        assert part.payload is not None
        assert part.payload["author_email"] == self.user.email
        assert part.route == {"channel": "C123", "thread_ts": "1700000000.000100"}
        assert part.client_msg_id

    @patch("products.conversations.backend.signals.wake_delivery_part")
    def test_private_slack_message_does_not_enqueue_slack_reply(self, mock_wake, mock_on_commit):
        self.team.conversations_settings = {"slack_enabled": True}
        self.team.save()
        slack_ticket = Ticket.objects.create_with_number(
            team=self.team,
            widget_session_id=self.widget_session_id,
            distinct_id="slack-user-2",
            channel_source=Channel.SLACK,
            slack_channel_id="C123",
            slack_thread_ts="1700000000.000200",
        )

        Comment.objects.create(
            team=self.team,
            scope="conversations_ticket",
            item_id=str(slack_ticket.id),
            content="Private support note",
            created_by=self.user,
            item_context={"author_type": "team", "is_private": True},
        )

        mock_wake.assert_not_called()

    @patch("products.conversations.backend.signals.wake_delivery_part")
    def test_customer_slack_message_does_not_enqueue_slack_reply(self, mock_wake, mock_on_commit):
        self.team.conversations_settings = {"slack_enabled": True}
        self.team.save()
        slack_ticket = Ticket.objects.create_with_number(
            team=self.team,
            widget_session_id=self.widget_session_id,
            distinct_id="slack-user-3",
            channel_source=Channel.SLACK,
            slack_channel_id="C123",
            slack_thread_ts="1700000000.000300",
        )

        Comment.objects.create(
            team=self.team,
            scope="conversations_ticket",
            item_id=str(slack_ticket.id),
            content="Customer message",
            item_context={"author_type": "customer", "is_private": False},
        )

        mock_wake.assert_not_called()

    @patch("products.conversations.backend.signals.invalidate_tickets_cache")
    def test_message_invalidates_tickets_cache(self, mock_invalidate, mock_on_commit):
        """Sending a message should invalidate the widget tickets cache."""
        self._create_customer_message("Hello")

        mock_invalidate.assert_called_once_with(self.team.id, self.widget_session_id)

    @patch("products.conversations.backend.signals.invalidate_messages_cache")
    def test_message_invalidates_messages_cache(self, mock_invalidate, mock_on_commit):
        """Sending a message should invalidate the widget messages cache."""
        self._create_customer_message("Hello")

        mock_invalidate.assert_called_once_with(self.team.id, str(self.ticket.id))

    @patch("products.conversations.backend.signals.invalidate_messages_cache")
    def test_private_message_does_not_invalidate_messages_cache(self, mock_invalidate, mock_on_commit):
        """Private messages should not invalidate the messages cache."""
        self._create_team_message("Private note", is_private=True)

        mock_invalidate.assert_not_called()

    @patch("products.conversations.backend.signals.invalidate_tickets_cache")
    def test_private_message_does_not_invalidate_cache(self, mock_invalidate, mock_on_commit):
        """Private messages should not invalidate the cache (they don't affect widget display)."""
        self._create_team_message("Private note", is_private=True)

        mock_invalidate.assert_not_called()


@patch.object(transaction, "on_commit", side_effect=immediate_on_commit)
class TestTicketCreatedEventSignal(BaseTest):
    """Tests for the post_save signal that emits `$conversation_ticket_created`."""

    def _make_ticket(self, **overrides) -> Ticket:
        defaults = {
            "team": self.team,
            "widget_session_id": str(uuid.uuid4()),
            "distinct_id": "user-123",
            "channel_source": Channel.WIDGET,
            "status": "new",
        }
        defaults.update(overrides)
        return Ticket.objects.create_with_number(**defaults)

    @parameterized.expand(
        [
            ("widget", Channel.WIDGET, {}),
            (
                "email",
                Channel.EMAIL,
                {
                    "distinct_id": "customer@example.com",
                    "anonymous_traits": {"name": "Customer", "email": "customer@example.com"},
                    "email_from": "customer@example.com",
                    "email_subject": "Help",
                },
            ),
            (
                "slack",
                Channel.SLACK,
                {"slack_channel_id": "C123", "slack_thread_ts": "1700000000.000100"},
            ),
            (
                "teams",
                Channel.TEAMS,
                {"teams_channel_id": "19:abc@thread.tacv2", "teams_conversation_id": "19:def@thread.tacv2"},
            ),
        ]
    )
    @patch("products.conversations.backend.signals.capture_ticket_created")
    def test_ticket_creation_emits_event_for_channel(self, _name, channel_source, extra, mock_capture, mock_on_commit):
        ticket = self._make_ticket(channel_source=channel_source, **extra)

        mock_capture.assert_called_once()
        emitted = mock_capture.call_args.args[0]
        assert emitted.id == ticket.id
        assert emitted.channel_source == channel_source

    @patch("products.conversations.backend.signals.capture_ticket_created")
    def test_ticket_update_does_not_emit_event(self, mock_capture, mock_on_commit):
        ticket = self._make_ticket()
        mock_capture.reset_mock()

        ticket.status = "open"
        ticket.save()

        mock_capture.assert_not_called()

    @patch("products.conversations.backend.signals.capture_ticket_created")
    def test_emit_swallows_capture_exceptions(self, mock_capture, mock_on_commit):
        """Analytics failures must not break ticket creation.

        With `transaction.on_commit` mocked to fire synchronously, the RuntimeError
        would propagate out of `_make_ticket` if the signal handler didn't swallow
        it — so the assertion that `_make_ticket` returns is the swallow check.
        """
        mock_capture.side_effect = RuntimeError("capture is down")

        ticket = self._make_ticket()

        assert ticket.id is not None
        mock_capture.assert_called_once()


@patch("products.conversations.backend.events.capture_internal")
class TestTicketTagAddedEventSignal(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.ticket = Ticket.objects.create_with_number(
            team=self.team,
            widget_session_id=str(uuid.uuid4()),
            distinct_id="user-123",
            channel_source=Channel.WIDGET,
        )

    def _task_kwargs(self) -> dict[str, Any]:
        return {
            "event": build_ticket_tag_added_event(self.ticket, str(uuid.uuid4()), "sf-lead"),
            "event_uuid": str(uuid.uuid4()),
            "timestamp": "2026-11-09T12:00:00+00:00",
        }

    @staticmethod
    def _tag_added_events(mock_capture: MagicMock) -> list[Mapping[str, Any]]:
        return [
            call.kwargs
            for call in mock_capture.call_args_list
            if call.kwargs["event_name"] == "$conversation_ticket_tag_added"
        ]

    @parameterized.expand(
        [
            ("new_tag", [], ["sf-lead"], "json", ["sf-lead"]),
            ("existing_tag", ["sf-lead"], ["sf-lead"], "json", []),
            ("two_new_tags", ["billing"], ["billing", "sf-lead", "urgent"], "json", ["sf-lead", "urgent"]),
            ("form_encoded_tag", [], ["sf-lead"], "multipart", ["sf-lead"]),
        ]
    )
    def test_ticket_patch_emits_one_event_per_new_tag(
        self, mock_capture, _name, existing_tags, patched_tags, request_format, expected_tags
    ):
        for name in existing_tags:
            self.ticket.tagged_items.create(tag=Tag.objects.create(name=name, team=self.team))

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.patch(
                f"/api/projects/{self.team.id}/conversations/tickets/{self.ticket.id}/",
                {"tags": patched_tags},
                format=request_format,
            )

        assert response.status_code == status.HTTP_200_OK, response.content
        emitted = sorted(
            (event["properties"]["tag"], event["properties"]["actor_type"], event["properties"]["actor_id"])
            for event in self._tag_added_events(mock_capture)
        )
        assert emitted == [(tag, "user", self.user.id) for tag in expected_tags]

    def test_workflow_patch_attributes_the_event_to_the_workflow(self, mock_capture):
        self.team.conversations_enabled = True
        self.team.save(update_fields=["conversations_enabled"])
        flow_id = "0191d3e0-0000-7000-8000-000000000001"
        token = CONVERSATIONS_TICKETS_PURPOSE.mint({"team_id": self.team.id, "ticket_id": str(self.ticket.id)})

        with self.captureOnCommitCallbacks(execute=True):
            response = APIClient().patch(
                f"/api/projects/{self.team.id}/internal/conversations/tickets/{self.ticket.id}",
                {"tags": ["sf-lead"]},
                format="json",
                HTTP_AUTHORIZATION=f"Bearer {token}",
                HTTP_X_POSTHOG_HOG_FLOW_ID=flow_id,
            )

        assert response.status_code == status.HTTP_200_OK, response.content
        [event] = self._tag_added_events(mock_capture)
        assert event["distinct_id"] == self.ticket.distinct_id
        assert {key: event["properties"][key] for key in ("tag", "actor_type", "actor_id", "workflow_id")} == {
            "tag": "sf-lead",
            "actor_type": "system",
            "actor_id": None,
            "workflow_id": flow_id,
        }

    @parameterized.expand(
        [
            (
                "bulk_create",
                lambda tag, ticket: TaggedItem.objects.bulk_create([TaggedItem.for_content_object(tag, ticket)]),
            ),
            (
                "other_model_with_the_ticket_uuid",
                lambda tag, ticket: TaggedItem.objects.create(
                    tag=tag, content_type_id=content_type_id_for_legacy_field("hog_flow"), object_uuid=ticket.id
                ),
            ),
        ]
    )
    def test_bulk_or_non_ticket_tag_rows_emit_nothing(self, mock_capture, _name, write_tag):
        tag = Tag.objects.create(name="sf-lead", team=self.team)

        with self.captureOnCommitCallbacks(execute=True):
            write_tag(tag, self.ticket)

        assert self._tag_added_events(mock_capture) == []

    def test_child_environment_ticket_emits_the_event(self, mock_capture):
        environment = Team.objects.create(organization=self.organization, project=self.project, parent_team=self.team)
        ticket = Ticket.objects.create_with_number(
            team=environment,
            widget_session_id=str(uuid.uuid4()),
            distinct_id="user-456",
            channel_source=Channel.WIDGET,
        )

        with self.captureOnCommitCallbacks(execute=True):
            ticket.tagged_items.get_or_create(tag=Tag.objects.create(name="sf-lead", team=environment))

        [event] = self._tag_added_events(mock_capture)
        assert (event["token"], event["properties"]["ticket_id"]) == (environment.api_token, str(ticket.id))

    def test_tagging_queues_the_capture_instead_of_sending_it_inline(self, mock_capture):
        tag = Tag.objects.create(name="sf-lead", team=self.team)

        with patch("products.conversations.backend.signals.emit_ticket_tag_added") as mock_task:
            with self.captureOnCommitCallbacks(execute=True):
                item, _ = self.ticket.tagged_items.get_or_create(tag=tag)

        mock_capture.assert_not_called()
        mock_task.delay.assert_called_once_with(
            event=build_ticket_tag_added_event(self.ticket, str(tag.id), "sf-lead"),
            event_uuid=str(item.id),
            timestamp=ANY,
        )

    def test_queued_event_keeps_the_ticket_as_it_was_when_tagged(self, mock_capture):
        with patch("products.conversations.backend.signals.emit_ticket_tag_added") as mock_task:
            with self.captureOnCommitCallbacks(execute=True):
                self.ticket.tagged_items.get_or_create(tag=Tag.objects.create(name="sf-lead", team=self.team))
        self.ticket.status = Status.RESOLVED
        self.ticket.save(update_fields=["status"])

        emit_ticket_tag_added(**mock_task.delay.call_args.kwargs)

        [event] = self._tag_added_events(mock_capture)
        assert event["properties"]["status"] == Status.NEW

    @parameterized.expand(
        [
            ("transport_error", CaptureInternalResult(status_code=0, error={"error": "transport_error"}), 0, "retry"),
            ("server_error", CaptureInternalResult(status_code=503, error={"error": "unavailable"}), 0, "retry"),
            ("rate_limited", CaptureInternalResult(status_code=429, error={"error": "rate_limited"}), 0, "retry"),
            ("request_timeout", CaptureInternalResult(status_code=408, error={"error": "timeout"}), 0, "retry"),
            ("bad_request", CaptureInternalResult(status_code=400, error={"error": "invalid"}), 0, "report"),
            ("billing_limited", CaptureInternalResult(status_code=402, error={"error": "billing_limit"}), 0, "skip"),
            ("dropped", CaptureInternalResult(status_code=200, dropped=["event"]), 0, "report"),
            ("retries_exhausted", CaptureInternalResult(status_code=503, error={"error": "unavailable"}), 5, "report"),
        ]
    )
    def test_task_retries_only_a_capture_that_can_succeed_later(self, mock_capture, _name, result, retries, outcome):
        mock_capture.return_value = result
        task_kwargs = self._task_kwargs()

        with patch("products.conversations.backend.tasks.ticket_events.capture_exception") as mock_report:
            with pytest.raises(Retry) if outcome == "retry" else nullcontext():
                cast(Any, emit_ticket_tag_added).apply(kwargs=task_kwargs, retries=retries)

        assert mock_report.called == (outcome == "report")
        sent = mock_capture.call_args.kwargs
        assert (sent["event_uuid"], sent["timestamp"]) == (task_kwargs["event_uuid"], task_kwargs["timestamp"])

    @parameterized.expand([("first_retry", 0, 60), ("third_retry", 2, 240)])
    def test_task_waits_longer_before_each_retry(self, mock_capture, _name, retries, wait_seconds):
        mock_capture.return_value = CaptureInternalResult(status_code=503, error={"error": "unavailable"})

        with pytest.raises(Retry) as retry:
            cast(Any, emit_ticket_tag_added).apply(kwargs=self._task_kwargs(), retries=retries)

        assert retry.value.when == wait_seconds

    def test_queueing_failure_does_not_break_the_tag_write(self, mock_capture):
        tag = Tag.objects.create(name="sf-lead", team=self.team)

        with patch("products.conversations.backend.signals.emit_ticket_tag_added") as mock_task:
            mock_task.delay.side_effect = ConnectionError("broker is down")
            with self.captureOnCommitCallbacks(execute=True):
                self.ticket.tagged_items.get_or_create(tag=tag)

        assert self.ticket.tagged_items.filter(tag=tag).exists()


@patch.object(transaction, "on_commit", side_effect=immediate_on_commit)
class TestEmailReplySignalGuard(BaseTest):
    def setUp(self):
        super().setUp()
        self.team.conversations_settings = {"email_enabled": True}
        self.team.save()
        self.config = EmailChannel.objects.create(
            team=self.team,
            inbound_token="signal0test1",
            from_email="support@example.com",
            from_name="Support",
            domain="example.com",
            domain_verified=True,
        )
        self.email_ticket = Ticket.objects.create_with_number(
            team=self.team,
            channel_source=Channel.EMAIL,
            email_config=self.config,
            widget_session_id="",
            distinct_id="customer@external.com",
            email_from="customer@external.com",
            email_subject="Help",
        )

    @parameterized.expand(
        [
            ("inbound_team_email_blocked", "support", True, True, 0),
            ("in_app_agent_reply_sent", "support", False, True, 1),
            ("customer_email_blocked", "customer", True, True, 0),
            ("workflow_public_reply_sent", "workflow", False, False, 1),
        ]
    )
    def test_email_outbox_guard(self, _mock_on_commit, _name, author_type, from_email, has_created_by, expected_count):
        ctx: dict = {"author_type": author_type, "is_private": False}
        if from_email:
            ctx["from_email"] = True

        Comment.objects.create(
            team=self.team,
            scope="conversations_ticket",
            item_id=str(self.email_ticket.id),
            content="test message",
            created_by=self.user if has_created_by else None,
            item_context=ctx,
        )

        assert EmailOutboxMessage.objects.filter(ticket=self.email_ticket).count() == expected_count


class TestIsOutboundReply:
    @parameterized.expand(
        [
            ("private_ai_note", {"author_type": "AI", "is_private": True}, None, False),
            ("public_ai_reply", {"author_type": "AI", "is_private": False}, None, True),
            ("public_workflow_reply", {"author_type": "workflow", "is_private": False}, None, True),
            ("private_workflow_note", {"author_type": "workflow", "is_private": True}, None, False),
            ("human_team_reply", {"author_type": "support", "is_private": False}, 42, True),
            ("private_human_note", {"author_type": "support", "is_private": True}, 42, False),
            ("customer_message", {"author_type": "customer", "is_private": False}, None, False),
            ("customer_with_created_by", {"author_type": "customer", "is_private": False}, 1, False),
            ("none_context", None, 42, False),
            ("non_dict_context", "garbage", None, False),
        ]
    )
    def test_outbound_reply_gating(self, _name, item_context, created_by_id, expected):
        from products.conversations.backend.signals import _is_outbound_reply

        assert _is_outbound_reply(item_context, created_by_id) is expected
