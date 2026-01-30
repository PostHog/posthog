import uuid

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.db import transaction

from posthog.models.comment import Comment

from products.conversations.backend.models import Ticket


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

    def test_customer_message_updates_stats(self, mock_on_commit):
        comment = self._create_customer_message("Hello from customer")

        self.ticket.refresh_from_db()
        assert self.ticket.message_count == 1
        assert self.ticket.last_message_at == comment.created_at
        assert self.ticket.last_message_text == "Hello from customer"
        assert self.ticket.unread_customer_count == 0  # Customer messages don't increment this

    def test_team_message_updates_stats_and_unread(self, mock_on_commit):
        comment = self._create_team_message("Response from team")

        self.ticket.refresh_from_db()
        assert self.ticket.message_count == 1
        assert self.ticket.last_message_at == comment.created_at
        assert self.ticket.last_message_text == "Response from team"
        assert self.ticket.unread_customer_count == 1  # Team messages increment this

    def test_multiple_messages_accumulate(self, mock_on_commit):
        self._create_customer_message("First")
        self._create_team_message("Second")
        last = self._create_customer_message("Third")

        self.ticket.refresh_from_db()
        assert self.ticket.message_count == 3
        assert self.ticket.last_message_at == last.created_at
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

        # Now send a private message - should not change last_message_*
        self._create_team_message("Private note for team only", is_private=True)

        self.ticket.refresh_from_db()
        assert self.ticket.message_count == 1  # Still 1
        assert self.ticket.last_message_text == "Public message"  # Unchanged
        assert self.ticket.last_message_at == public_msg.created_at  # Unchanged

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
