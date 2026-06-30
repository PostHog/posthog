from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, call, patch

from parameterized import parameterized

from posthog.models.comment import Comment

from products.conversations.backend.cache import slack_ticket_create_lock
from products.conversations.backend.models import Ticket
from products.conversations.backend.models.constants import Channel, ChannelDetail
from products.conversations.backend.slack import (
    _backfill_thread_replies,
    create_or_update_slack_ticket,
    handle_support_reaction,
)


def _make_slack_reply(ts: str, user: str = "U_REPLY", text: str = "reply text", **extra) -> dict:
    msg: dict = {"ts": ts, "user": user, "text": text}
    msg.update(extra)
    return msg


PARENT_TS = "1700000000.000100"
CHANNEL = "C_SUPPORT"
SLACK_TEAM = "T123"

MODULE = "products.conversations.backend.slack"


class TestBackfillThreadReplies(BaseTest):
    def setUp(self):
        super().setUp()
        self.team.conversations_settings = {"slack_enabled": True}
        self.team.save()
        self.ticket = Ticket.objects.create_with_number(
            team=self.team,
            channel_source=Channel.SLACK,
            widget_session_id="",
            distinct_id="",
            slack_channel_id=CHANNEL,
            slack_thread_ts=PARENT_TS,
            unread_team_count=1,
        )

    def _mock_client(self, replies: list[dict]) -> MagicMock:
        client = MagicMock()
        client.conversations_replies.return_value = {"messages": replies}
        return client

    @patch(f"{MODULE}.get_bot_user_id", return_value="U_OWN_BOT")
    @patch(f"{MODULE}.resolve_slack_user", return_value={"name": "Alice", "email": "a@x.com", "avatar": None})
    @patch(f"{MODULE}.extract_slack_files", return_value=[])
    def test_backfills_thread_replies_as_comments(self, _mock_files, _mock_user, _mock_bot):
        replies = [
            _make_slack_reply(PARENT_TS, text="parent"),
            _make_slack_reply("1700000000.000200", user="U1", text="first reply"),
            _make_slack_reply("1700000000.000300", user="U2", text="second reply"),
        ]
        client = self._mock_client(replies)

        _backfill_thread_replies(client, self.team, self.ticket, CHANNEL, PARENT_TS)

        comments = Comment.objects.filter(item_id=str(self.ticket.id)).order_by("created_at")
        assert comments.count() == 2
        assert comments[0].content == "first reply"
        assert comments[1].content == "second reply"

        self.ticket.refresh_from_db()
        assert self.ticket.unread_team_count == 3  # 1 original + 2 backfilled

    @patch(f"{MODULE}.get_bot_user_id", return_value="U_OWN_BOT")
    @patch(f"{MODULE}.resolve_slack_user", return_value={"name": "Alice", "email": "a@x.com", "avatar": None})
    @patch(f"{MODULE}.extract_slack_files", return_value=[])
    def test_calls_conversations_replies_with_correct_args(self, _mock_files, _mock_user, _mock_bot):
        replies = [
            _make_slack_reply(PARENT_TS, text="parent"),
            _make_slack_reply("1700000000.000200", text="reply"),
        ]
        client = self._mock_client(replies)

        _backfill_thread_replies(client, self.team, self.ticket, CHANNEL, PARENT_TS)

        client.conversations_replies.assert_called_once_with(channel=CHANNEL, ts=PARENT_TS, limit=200)

    @parameterized.expand(
        [
            ("message_changed_subtype", {"subtype": "message_changed"}),
            ("message_deleted_subtype", {"subtype": "message_deleted"}),
        ]
    )
    @patch(f"{MODULE}.get_bot_user_id", return_value="U_OWN_BOT")
    @patch(f"{MODULE}.resolve_slack_user", return_value={"name": "Alice", "email": None, "avatar": None})
    @patch(f"{MODULE}.extract_slack_files", return_value=[])
    def test_skips_non_message_subtypes(self, _name, extra_fields, _mock_files, _mock_user, _mock_bot):
        replies = [
            _make_slack_reply(PARENT_TS, text="parent"),
            _make_slack_reply("1700000000.000200", text="filtered", **extra_fields),
            _make_slack_reply("1700000000.000300", text="human reply"),
        ]
        client = self._mock_client(replies)

        _backfill_thread_replies(client, self.team, self.ticket, CHANNEL, PARENT_TS)

        comments = Comment.objects.filter(item_id=str(self.ticket.id))
        assert comments.count() == 1
        assert comments[0].content == "human reply"

    @parameterized.expand(
        [
            ("bot_id", {"bot_id": "B_OTHER"}),
            ("bot_message_subtype", {"subtype": "bot_message"}),
        ]
    )
    @patch(f"{MODULE}.get_bot_user_id", return_value="U_OWN_BOT")
    @patch(f"{MODULE}.resolve_slack_user", return_value={"name": "OtherBot", "email": None, "avatar": None})
    @patch(f"{MODULE}.extract_slack_files", return_value=[])
    def test_allows_other_bot_replies(self, _name, extra_fields, _mock_files, _mock_user, _mock_bot):
        replies = [
            _make_slack_reply(PARENT_TS, text="parent"),
            _make_slack_reply("1700000000.000200", user="U_OTHER_BOT", text="bot reply", **extra_fields),
        ]
        client = self._mock_client(replies)

        _backfill_thread_replies(client, self.team, self.ticket, CHANNEL, PARENT_TS)

        comments = Comment.objects.filter(item_id=str(self.ticket.id))
        assert comments.count() == 1
        assert comments[0].content == "bot reply"

    @patch(f"{MODULE}.get_bot_user_id", return_value="U_OWN_BOT")
    @patch(f"{MODULE}.resolve_slack_user", return_value={"name": "OurBot", "email": None, "avatar": None})
    @patch(f"{MODULE}.extract_slack_files", return_value=[])
    def test_skips_own_bot_replies(self, _mock_files, _mock_user, _mock_bot):
        replies = [
            _make_slack_reply(PARENT_TS, text="parent"),
            _make_slack_reply("1700000000.000200", user="U_OWN_BOT", text="Ticket #1 created", bot_id="B_OWN"),
            _make_slack_reply("1700000000.000300", text="human reply"),
        ]
        client = self._mock_client(replies)

        _backfill_thread_replies(client, self.team, self.ticket, CHANNEL, PARENT_TS)

        comments = Comment.objects.filter(item_id=str(self.ticket.id))
        assert comments.count() == 1
        assert comments[0].content == "human reply"

    @patch(f"{MODULE}.get_bot_user_id", return_value="U_OWN_BOT")
    @patch(f"{MODULE}.resolve_slack_user", return_value={"name": "Alice", "email": None, "avatar": None})
    @patch(f"{MODULE}.extract_slack_files", return_value=[])
    def test_skips_empty_replies(self, _mock_files, _mock_user, _mock_bot):
        replies = [
            _make_slack_reply(PARENT_TS, text="parent"),
            _make_slack_reply("1700000000.000200", text="   "),
            _make_slack_reply("1700000000.000300", text="real reply"),
        ]
        client = self._mock_client(replies)

        _backfill_thread_replies(client, self.team, self.ticket, CHANNEL, PARENT_TS)

        comments = Comment.objects.filter(item_id=str(self.ticket.id))
        assert comments.count() == 1

    @patch(f"{MODULE}.get_bot_user_id", return_value="U_OWN_BOT")
    @patch(f"{MODULE}.resolve_slack_user", return_value={"name": "Alice", "email": None, "avatar": None})
    @patch(f"{MODULE}.extract_slack_files")
    def test_includes_file_only_replies(self, mock_files, _mock_user, _mock_bot):
        mock_files.return_value = [{"url": "https://example.com/img.png", "name": "img.png", "mimetype": "image/png"}]
        replies = [
            _make_slack_reply(PARENT_TS, text="parent"),
            _make_slack_reply(
                "1700000000.000200",
                text="",
                files=[{"id": "F1", "mimetype": "image/png", "url_private": "https://files.slack.com/img.png"}],
            ),
        ]
        client = self._mock_client(replies)

        _backfill_thread_replies(client, self.team, self.ticket, CHANNEL, PARENT_TS)

        comments = Comment.objects.filter(item_id=str(self.ticket.id))
        assert comments.count() == 1
        assert comments[0].item_context["slack_images"] is not None

    @patch(f"{MODULE}.get_bot_user_id", return_value="U_OWN_BOT")
    @patch(f"{MODULE}.resolve_slack_user")
    @patch(f"{MODULE}.extract_slack_files", return_value=[])
    def test_caches_user_lookups(self, _mock_files, mock_user, _mock_bot):
        mock_user.return_value = {"name": "Alice", "email": None, "avatar": None}
        replies = [
            _make_slack_reply(PARENT_TS, text="parent"),
            _make_slack_reply("1700000000.000200", user="U_SAME", text="reply 1"),
            _make_slack_reply("1700000000.000300", user="U_SAME", text="reply 2"),
            _make_slack_reply("1700000000.000400", user="U_OTHER", text="reply 3"),
        ]
        client = self._mock_client(replies)

        _backfill_thread_replies(client, self.team, self.ticket, CHANNEL, PARENT_TS)

        assert mock_user.call_count == 2
        mock_user.assert_has_calls([call(client, "U_SAME"), call(client, "U_OTHER")], any_order=True)

    @patch(f"{MODULE}.get_bot_user_id", return_value="U_OWN_BOT")
    @patch(f"{MODULE}.resolve_slack_user", return_value={"name": "Alice", "email": None, "avatar": None})
    @patch(f"{MODULE}.extract_slack_files", return_value=[])
    def test_after_ts_excludes_earlier_replies(self, _mock_files, _mock_user, _mock_bot):
        replies = [
            _make_slack_reply(PARENT_TS, text="parent"),
            _make_slack_reply("1700000000.000200", text="before reacted"),
            _make_slack_reply("1700000000.000300", text="reacted message"),
            _make_slack_reply("1700000000.000400", text="after reacted"),
        ]
        client = self._mock_client(replies)

        _backfill_thread_replies(client, self.team, self.ticket, CHANNEL, PARENT_TS, after_ts="1700000000.000300")

        comments = Comment.objects.filter(item_id=str(self.ticket.id)).order_by("created_at")
        assert comments.count() == 1
        assert comments[0].content == "after reacted"

    def test_no_op_when_only_parent_in_thread(self):
        replies = [_make_slack_reply(PARENT_TS, text="parent")]
        client = self._mock_client(replies)

        _backfill_thread_replies(client, self.team, self.ticket, CHANNEL, PARENT_TS)

        assert Comment.objects.filter(item_id=str(self.ticket.id)).count() == 0
        self.ticket.refresh_from_db()
        assert self.ticket.unread_team_count == 1

    def test_no_op_when_api_returns_empty_messages(self):
        client = self._mock_client([])

        _backfill_thread_replies(client, self.team, self.ticket, CHANNEL, PARENT_TS)

        assert Comment.objects.filter(item_id=str(self.ticket.id)).count() == 0
        self.ticket.refresh_from_db()
        assert self.ticket.unread_team_count == 1

    def test_handles_conversations_replies_api_failure(self):
        client = MagicMock()
        client.conversations_replies.side_effect = Exception("Slack API error")

        _backfill_thread_replies(client, self.team, self.ticket, CHANNEL, PARENT_TS)

        assert Comment.objects.filter(item_id=str(self.ticket.id)).count() == 0
        self.ticket.refresh_from_db()
        assert self.ticket.unread_team_count == 1

    @patch(f"{MODULE}.get_bot_user_id", return_value="U_OWN_BOT")
    @patch(f"{MODULE}.resolve_slack_user", return_value={"name": "Bob", "email": "b@x.com", "avatar": "http://av"})
    @patch(f"{MODULE}.extract_slack_files", return_value=[])
    def test_stores_slack_user_info_in_item_context(self, _mock_files, _mock_user, _mock_bot):
        replies = [
            _make_slack_reply(PARENT_TS, text="parent"),
            _make_slack_reply("1700000000.000200", user="U_BOB", text="hello"),
        ]
        client = self._mock_client(replies)

        _backfill_thread_replies(client, self.team, self.ticket, CHANNEL, PARENT_TS)

        comment = Comment.objects.get(item_id=str(self.ticket.id))
        assert comment.item_context == {
            "author_type": "customer",
            "is_private": False,
            "from_slack": True,
            "slack_user_id": "U_BOB",
            "slack_author_name": "Bob",
            "slack_author_email": "b@x.com",
            "slack_author_avatar": "http://av",
            "slack_images": None,
        }


class TestHandleSupportReactionBackfill(BaseTest):
    def setUp(self):
        super().setUp()
        self.team.conversations_settings = {
            "slack_enabled": True,
            "slack_ticket_emoji": "ticket",
        }
        self.team.save()

    def _reaction_event(self, reaction: str = "ticket", channel: str = CHANNEL, ts: str = PARENT_TS) -> dict:
        return {
            "type": "reaction_added",
            "reaction": reaction,
            "item": {"channel": channel, "ts": ts},
            "user": "U_REACTOR",
        }

    @patch(f"{MODULE}._backfill_thread_replies")
    @patch(f"{MODULE}.create_or_update_slack_ticket")
    @patch(f"{MODULE}.get_slack_client")
    def test_calls_backfill_after_ticket_creation(self, mock_client, mock_create, mock_backfill):
        client = MagicMock()
        client.conversations_replies.return_value = {"messages": [{"user": "U1", "text": "Help me", "ts": PARENT_TS}]}
        mock_client.return_value = client
        mock_create.return_value = MagicMock(spec=Ticket)

        handle_support_reaction(self._reaction_event(), self.team, SLACK_TEAM)

        mock_create.assert_called_once()
        assert mock_create.call_args.kwargs["is_thread_reply"] is False
        assert mock_create.call_args.kwargs["thread_ts"] == PARENT_TS
        mock_backfill.assert_called_once_with(
            client, self.team, mock_create.return_value, CHANNEL, PARENT_TS, after_ts=PARENT_TS
        )

    @patch(f"{MODULE}._backfill_thread_replies")
    @patch(f"{MODULE}.create_or_update_slack_ticket")
    @patch(f"{MODULE}.get_slack_client")
    def test_seeds_ticket_from_reacted_reply_keyed_on_root(self, mock_client, mock_create, mock_backfill):
        reply_ts = "1700000000.000500"
        client = MagicMock()
        # conversations.replies returns the root first regardless of which message was reacted on.
        client.conversations_replies.return_value = {
            "messages": [
                {"user": "U_ROOT", "text": "Hi Mustafa!", "ts": PARENT_TS},
                {"user": "U_CUSTOMER", "text": "here are the screenshots", "ts": reply_ts, "thread_ts": PARENT_TS},
            ]
        }
        mock_client.return_value = client
        mock_create.return_value = MagicMock(spec=Ticket)

        handle_support_reaction(self._reaction_event(ts=reply_ts), self.team, SLACK_TEAM)

        # Ticket seeds from the reacted reply, but is keyed on the thread root for routing.
        assert mock_create.call_args.kwargs["thread_ts"] == PARENT_TS
        assert mock_create.call_args.kwargs["text"] == "here are the screenshots"
        assert mock_create.call_args.kwargs["slack_user_id"] == "U_CUSTOMER"
        # Backfill only replies posted after the reacted message.
        mock_backfill.assert_called_once_with(
            client, self.team, mock_create.return_value, CHANNEL, PARENT_TS, after_ts=reply_ts
        )
        # We must never fetch via conversations.history (it can't see thread replies).
        client.conversations_history.assert_not_called()

    @patch(f"{MODULE}._backfill_thread_replies")
    @patch(f"{MODULE}.create_or_update_slack_ticket")
    @patch(f"{MODULE}.get_slack_client")
    def test_resolves_root_from_thread_ts_when_replies_returns_only_reply(
        self, mock_client, mock_create, mock_backfill
    ):
        # Hardening for the case where conversations.replies returns only the reacted reply
        # (not the root-first thread): the root must still come from the reply's thread_ts.
        reply_ts = "1700000000.000500"
        client = MagicMock()
        client.conversations_replies.return_value = {
            "messages": [
                {"user": "U_CUSTOMER", "text": "screenshots", "ts": reply_ts, "thread_ts": PARENT_TS},
            ]
        }
        mock_client.return_value = client
        mock_create.return_value = MagicMock(spec=Ticket)

        handle_support_reaction(self._reaction_event(ts=reply_ts), self.team, SLACK_TEAM)

        assert mock_create.call_args.kwargs["thread_ts"] == PARENT_TS
        assert mock_create.call_args.kwargs["text"] == "screenshots"
        mock_backfill.assert_called_once_with(
            client, self.team, mock_create.return_value, CHANNEL, PARENT_TS, after_ts=reply_ts
        )

    @patch(f"{MODULE}._backfill_thread_replies")
    @patch(f"{MODULE}.create_or_update_slack_ticket")
    @patch(f"{MODULE}.get_slack_client")
    def test_falls_back_to_bounded_history_for_standalone_message(self, mock_client, mock_create, mock_backfill):
        client = MagicMock()
        client.conversations_replies.return_value = {"messages": []}
        client.conversations_history.return_value = {"messages": [{"user": "U1", "text": "Help me", "ts": PARENT_TS}]}
        mock_client.return_value = client
        mock_create.return_value = MagicMock(spec=Ticket)

        handle_support_reaction(self._reaction_event(), self.team, SLACK_TEAM)

        client.conversations_history.assert_called_once_with(
            channel=CHANNEL, latest=PARENT_TS, oldest=PARENT_TS, inclusive=True, limit=1
        )
        assert mock_create.call_args.kwargs["thread_ts"] == PARENT_TS
        mock_backfill.assert_called_once_with(
            client, self.team, mock_create.return_value, CHANNEL, PARENT_TS, after_ts=PARENT_TS
        )

    @patch(f"{MODULE}._backfill_thread_replies")
    @patch(f"{MODULE}.create_or_update_slack_ticket")
    @patch(f"{MODULE}.get_slack_client")
    def test_skips_when_ticket_already_exists_for_resolved_root(self, mock_client, mock_create, mock_backfill):
        reply_ts = "1700000000.000500"
        Ticket.objects.create_with_number(
            team=self.team,
            channel_source=Channel.SLACK,
            widget_session_id="",
            distinct_id="",
            slack_channel_id=CHANNEL,
            slack_thread_ts=PARENT_TS,
        )
        client = MagicMock()
        client.conversations_replies.return_value = {
            "messages": [
                {"user": "U_ROOT", "text": "Hi Mustafa!", "ts": PARENT_TS},
                {"user": "U_CUSTOMER", "text": "screenshots", "ts": reply_ts, "thread_ts": PARENT_TS},
            ]
        }
        mock_client.return_value = client

        handle_support_reaction(self._reaction_event(ts=reply_ts), self.team, SLACK_TEAM)

        mock_create.assert_not_called()
        mock_backfill.assert_not_called()

    @patch(f"{MODULE}._backfill_thread_replies")
    @patch(f"{MODULE}.create_or_update_slack_ticket")
    @patch(f"{MODULE}.get_slack_client")
    def test_skips_backfill_when_ticket_creation_returns_none(self, mock_client, mock_create, mock_backfill):
        client = MagicMock()
        client.conversations_replies.return_value = {"messages": [{"user": "U1", "text": "Help me", "ts": PARENT_TS}]}
        mock_client.return_value = client
        mock_create.return_value = None

        handle_support_reaction(self._reaction_event(), self.team, SLACK_TEAM)

        mock_backfill.assert_not_called()

    @patch(f"{MODULE}._backfill_thread_replies")
    @patch(f"{MODULE}.create_or_update_slack_ticket")
    @patch(f"{MODULE}.get_slack_client")
    def test_skips_backfill_when_ticket_already_exists(self, mock_client, mock_create, mock_backfill):
        Ticket.objects.create_with_number(
            team=self.team,
            channel_source=Channel.SLACK,
            widget_session_id="",
            distinct_id="",
            slack_channel_id=CHANNEL,
            slack_thread_ts=PARENT_TS,
        )

        handle_support_reaction(self._reaction_event(), self.team, SLACK_TEAM)

        mock_client.assert_not_called()
        mock_create.assert_not_called()
        mock_backfill.assert_not_called()

    @patch(f"{MODULE}._backfill_thread_replies")
    @patch(f"{MODULE}.create_or_update_slack_ticket")
    @patch(f"{MODULE}.get_slack_client")
    def test_skips_backfill_for_wrong_emoji(self, mock_client, mock_create, mock_backfill):
        handle_support_reaction(self._reaction_event(reaction="thumbsup"), self.team, SLACK_TEAM)

        mock_client.assert_not_called()
        mock_create.assert_not_called()
        mock_backfill.assert_not_called()


class TestSlackTicketCreateLockDedup(BaseTest):
    """Verify that the Redis lock in create_or_update_slack_ticket prevents duplicate tickets."""

    def setUp(self):
        super().setUp()
        self.team.conversations_settings = {"slack_enabled": True}
        self.team.save()

    @patch(f"{MODULE}.get_slack_client")
    @patch(f"{MODULE}.resolve_slack_user", return_value={"name": "Alice", "email": "a@x.com", "avatar": None})
    @patch(f"{MODULE}.extract_slack_files", return_value=[])
    def test_second_call_returns_none_when_first_already_created(self, _files, _user, mock_client):
        mock_client.return_value = MagicMock()
        mock_client.return_value.chat_postMessage = MagicMock()

        kwargs: dict[str, Any] = {
            "team": self.team,
            "slack_channel_id": CHANNEL,
            "thread_ts": PARENT_TS,
            "slack_user_id": "U_SOMEONE",
            "text": "Help me please",
            "is_thread_reply": False,
            "slack_team_id": SLACK_TEAM,
            "channel_detail": ChannelDetail.SLACK_EMOJI_REACTION,
        }

        # First call creates the ticket
        ticket1 = create_or_update_slack_ticket(**kwargs)
        # Second call hits the re-check inside the lock and returns None (not the existing
        # ticket) so callers don't re-run backfill side effects.
        ticket2 = create_or_update_slack_ticket(**kwargs)

        tickets = Ticket.objects.filter(team=self.team, slack_channel_id=CHANNEL, slack_thread_ts=PARENT_TS)
        assert tickets.count() == 1
        assert ticket1 is not None
        assert ticket2 is None
        # Only one confirmation message posted (second call short-circuits)
        assert mock_client.return_value.chat_postMessage.call_count == 1

    @patch(f"{MODULE}.get_slack_client")
    @patch(f"{MODULE}.resolve_slack_user", return_value={"name": "Bob", "email": "b@x.com", "avatar": None})
    @patch(f"{MODULE}.extract_slack_files", return_value=[])
    def test_lock_held_returns_without_creating_duplicate(self, _files, _user, mock_client):
        mock_client.return_value = MagicMock()

        # Pre-acquire the lock via production code to simulate a concurrent worker holding it
        with slack_ticket_create_lock(self.team.id, CHANNEL, PARENT_TS) as acquired:
            assert acquired

            result = create_or_update_slack_ticket(
                team=self.team,
                slack_channel_id=CHANNEL,
                thread_ts=PARENT_TS,
                slack_user_id="U_SOMEONE",
                text="Help!",
                is_thread_reply=False,
                slack_team_id=SLACK_TEAM,
                channel_detail=ChannelDetail.SLACK_EMOJI_REACTION,
            )

            # No ticket created — lock was held
            assert (
                Ticket.objects.filter(team=self.team, slack_channel_id=CHANNEL, slack_thread_ts=PARENT_TS).count() == 0
            )
            assert result is None
            # No confirmation posted
            mock_client.return_value.chat_postMessage.assert_not_called()

    @patch(f"{MODULE}.get_bot_user_id", return_value="U_BOT")
    @patch(f"{MODULE}.get_slack_client")
    @patch(f"{MODULE}.resolve_slack_user", return_value={"name": "Cara", "email": "c@x.com", "avatar": None})
    @patch(f"{MODULE}.extract_slack_files", return_value=[])
    def test_dedup_create_returns_none_so_caller_skips_backfill(self, _files, _user, mock_client, _bot):
        # Reproduces the race where two reaction events both pass handle_support_reaction's
        # .exists() fast-path, then both reach create. The caller backfills only when create
        # returns a ticket — so the loser must get None or the backfill duplicates comments.
        reply_ts = "1700000000.000500"
        client = MagicMock()
        client.conversations_replies.return_value = {
            "messages": [
                {"user": "U_ROOT", "text": "Help me please", "ts": PARENT_TS},
                {"user": "U_CUSTOMER", "text": "more context", "ts": reply_ts, "thread_ts": PARENT_TS},
            ]
        }
        mock_client.return_value = client

        kwargs: dict[str, Any] = {
            "team": self.team,
            "slack_channel_id": CHANNEL,
            "thread_ts": PARENT_TS,
            "slack_user_id": "U_ROOT",
            "text": "Help me please",
            "is_thread_reply": False,
            "slack_team_id": SLACK_TEAM,
            "channel_detail": ChannelDetail.SLACK_EMOJI_REACTION,
        }

        # Mirror handle_support_reaction: create, then backfill iff a ticket came back.
        for _ in range(2):
            ticket = create_or_update_slack_ticket(**kwargs)
            if ticket:
                _backfill_thread_replies(client, self.team, ticket, CHANNEL, PARENT_TS, after_ts=PARENT_TS)

        tickets = Ticket.objects.filter(team=self.team, slack_channel_id=CHANNEL, slack_thread_ts=PARENT_TS)
        assert tickets.count() == 1
        created_ticket = tickets.first()
        assert created_ticket is not None
        # One seed comment + one backfilled reply. The duplicate call returns None, so backfill
        # runs only once and comments aren't doubled.
        comments = Comment.objects.filter(scope="conversations_ticket", item_id=str(created_ticket.id))
        assert comments.count() == 2
