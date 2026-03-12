from posthog.test.base import BaseTest
from unittest.mock import MagicMock, call, patch

from parameterized import parameterized

from posthog.models.comment import Comment

from products.conversations.backend.models import Ticket
from products.conversations.backend.models.constants import Channel
from products.conversations.backend.slack import _backfill_thread_replies, handle_support_reaction


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

    @patch(f"{MODULE}.resolve_slack_user", return_value={"name": "Alice", "email": "a@x.com", "avatar": None})
    @patch(f"{MODULE}.extract_slack_files", return_value=[])
    def test_backfills_thread_replies_as_comments(self, _mock_files, _mock_user):
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

    @patch(f"{MODULE}.resolve_slack_user", return_value={"name": "Alice", "email": "a@x.com", "avatar": None})
    @patch(f"{MODULE}.extract_slack_files", return_value=[])
    def test_calls_conversations_replies_with_correct_args(self, _mock_files, _mock_user):
        replies = [
            _make_slack_reply(PARENT_TS, text="parent"),
            _make_slack_reply("1700000000.000200", text="reply"),
        ]
        client = self._mock_client(replies)

        _backfill_thread_replies(client, self.team, self.ticket, CHANNEL, PARENT_TS)

        client.conversations_replies.assert_called_once_with(channel=CHANNEL, ts=PARENT_TS, limit=200)

    @parameterized.expand(
        [
            ("bot_id", {"bot_id": "B123"}),
            ("bot_message_subtype", {"subtype": "bot_message"}),
            ("message_changed_subtype", {"subtype": "message_changed"}),
            ("message_deleted_subtype", {"subtype": "message_deleted"}),
        ]
    )
    @patch(f"{MODULE}.resolve_slack_user", return_value={"name": "Alice", "email": None, "avatar": None})
    @patch(f"{MODULE}.extract_slack_files", return_value=[])
    def test_skips_filtered_message_types(self, _name, extra_fields, _mock_files, _mock_user):
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

    @patch(f"{MODULE}.resolve_slack_user", return_value={"name": "Alice", "email": None, "avatar": None})
    @patch(f"{MODULE}.extract_slack_files", return_value=[])
    def test_skips_empty_replies(self, _mock_files, _mock_user):
        replies = [
            _make_slack_reply(PARENT_TS, text="parent"),
            _make_slack_reply("1700000000.000200", text="   "),
            _make_slack_reply("1700000000.000300", text="real reply"),
        ]
        client = self._mock_client(replies)

        _backfill_thread_replies(client, self.team, self.ticket, CHANNEL, PARENT_TS)

        comments = Comment.objects.filter(item_id=str(self.ticket.id))
        assert comments.count() == 1

    @patch(f"{MODULE}.resolve_slack_user", return_value={"name": "Alice", "email": None, "avatar": None})
    @patch(f"{MODULE}.extract_slack_files")
    def test_includes_file_only_replies(self, mock_files, _mock_user):
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

    @patch(f"{MODULE}.resolve_slack_user")
    @patch(f"{MODULE}.extract_slack_files", return_value=[])
    def test_caches_user_lookups(self, _mock_files, mock_user):
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

    @patch(f"{MODULE}.resolve_slack_user", return_value={"name": "Bob", "email": "b@x.com", "avatar": "http://av"})
    @patch(f"{MODULE}.extract_slack_files", return_value=[])
    def test_stores_slack_user_info_in_item_context(self, _mock_files, _mock_user):
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
        client.conversations_history.return_value = {"messages": [{"user": "U1", "text": "Help me", "ts": PARENT_TS}]}
        mock_client.return_value = client
        mock_create.return_value = MagicMock(spec=Ticket)

        handle_support_reaction(self._reaction_event(), self.team, SLACK_TEAM)

        mock_create.assert_called_once()
        assert mock_create.call_args.kwargs["is_thread_reply"] is False
        mock_backfill.assert_called_once_with(client, self.team, mock_create.return_value, CHANNEL, PARENT_TS)

    @patch(f"{MODULE}._backfill_thread_replies")
    @patch(f"{MODULE}.create_or_update_slack_ticket")
    @patch(f"{MODULE}.get_slack_client")
    def test_skips_backfill_when_ticket_creation_returns_none(self, mock_client, mock_create, mock_backfill):
        client = MagicMock()
        client.conversations_history.return_value = {"messages": [{"user": "U1", "text": "Help me", "ts": PARENT_TS}]}
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
