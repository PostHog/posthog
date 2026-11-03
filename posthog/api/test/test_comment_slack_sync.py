from datetime import timedelta
from uuid import UUID

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.apps import apps
from django.core.cache import cache
from django.test import SimpleTestCase
from django.utils import timezone

from celery.exceptions import Retry
from parameterized import parameterized
from rest_framework import status
from slack_sdk.errors import SlackApiError

from posthog.api.comments import _slack_thread_url
from posthog.helpers.slack_thread_mirror import _discussion_card_blocks
from posthog.models import Team
from posthog.models.comment import Comment, CommentSlackThread
from posthog.models.comment.comment import OBSERVATION_COMMENT_SCOPES
from posthog.models.integration import Integration
from posthog.tasks.comment_slack_sync import (
    BACKFILL_BATCH_SIZE,
    BACKFILL_RESCHEDULE_COUNTDOWN_SECONDS,
    LINKED_THREAD_IMPORT_MESSAGE_LIMIT,
    SLACK_SYNCED_TS_KEY,
    backfill_comment_slack_thread,
    import_linked_slack_thread,
    ingest_slack_discussion_reply,
    mirror_comment_reply_to_slack,
)

from products.canvas.backend.facade import testing as canvas_testing
from products.conversations.backend.models import PurgedTicketThread, Ticket
from products.conversations.backend.models.constants import Channel, Status
from products.conversations.backend.models.purged_ticket_thread import ticket_thread_key


class TestDiscussionCardBlocks(SimpleTestCase):
    def _card_text(self, body: str) -> str:
        blocks = _discussion_card_blocks(
            body_mrkdwn=body, author_name="Ann", item_url="https://app.posthog.com/i/1", item_label="Insight"
        )
        return blocks[0]["text"]["text"]

    def test_every_line_of_a_multiline_body_stays_in_the_quote(self):
        # mrkdwn's ">" quotes one line, so without a prefix per line the tail of a comment
        # renders as the card's own text rather than as the quoted comment.
        text = self._card_text("first line\nsecond line\n\nfourth line")

        quoted = text.split("in PostHog:\n\n", 1)[1]
        assert quoted == "> first line\n> second line\n> \n> fourth line"

    def test_empty_body_still_renders_a_quoted_placeholder(self):
        assert self._card_text("").endswith("> _(no text)_")


class TestSendCommentToSlack(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.integration = Integration.objects.create(
            team=self.team,
            kind="slack",
            integration_id="T123",
            config={"authed_user": {"id": "u"}},
            sensitive_config={"access_token": "xoxb-test"},
        )

    def _comment(self, **kwargs) -> Comment:
        defaults: dict = {
            "team": self.team,
            "scope": "Insight",
            "item_id": "42",
            "content": "hello",
            "created_by": self.user,
        }
        defaults.update(kwargs)
        return Comment.objects.create(**defaults)

    @parameterized.expand(
        [
            # ts dot stripped, archives permalink form
            ("with_ts", "1700.1", "https://app.slack.com/archives/C1/p17001"),
            # not yet posted: link to the channel
            ("no_ts", "", "https://app.slack.com/archives/C1"),
        ]
    )
    def test_slack_thread_url(self, _name, ts, expected):
        thread = CommentSlackThread(slack_channel_id="C1", slack_thread_ts=ts, slack_team_id="T123")
        assert _slack_thread_url(thread) == expected

    def _send(self, comment_id, channel_id: str = "C1", integration_id: int | None = None, extra: dict | None = None):
        return self.client.post(
            f"/api/projects/{self.team.id}/comments/{comment_id}/send_to_slack/",
            {
                "integration_id": integration_id or self.integration.id,
                "channel_id": channel_id,
                **(extra or {}),
            },
        )

    def _mock_channel_info(self, mock_slack, name: str = "team-support", is_private: bool = False, **flags) -> None:
        mock_slack.return_value.client.conversations_info.return_value = {
            "channel": {"id": "C1", "name": name, "is_private": is_private, **flags}
        }

    @parameterized.expand([("dm", {"is_im": True}), ("group_dm", {"is_mpim": True, "is_private": True})])
    @patch("posthog.api.comments.backfill_comment_slack_thread.delay")
    @patch("posthog.api.comments.posthoganalytics.feature_enabled", return_value=True)
    @patch("posthog.api.comments.SlackIntegration")
    def test_cannot_send_to_a_direct_message(self, _name, flags, mock_slack, _flag, _backfill):
        # is_im conversations don't report is_private, so without an explicit guard a member
        # could mirror a discussion into someone's DMs with the bot.
        self._mock_channel_info(mock_slack, **flags)
        comment = self._comment()

        res = self._send(comment.id, channel_id="D1")

        assert res.status_code == status.HTTP_400_BAD_REQUEST
        assert "direct message" in str(res.json())
        assert not CommentSlackThread.objects.for_team(self.team.id).exists()
        mock_slack.return_value.client.chat_postMessage.assert_not_called()

    @patch("posthog.api.comments.backfill_comment_slack_thread.delay")
    @patch("posthog.api.comments.posthoganalytics.feature_enabled", return_value=True)
    @patch("posthog.api.comments.SlackIntegration")
    def test_creates_mirror_posts_root_and_enqueues_backfill(self, mock_slack, _flag, mock_backfill):
        mock_slack.return_value.client.chat_postMessage.return_value = {"ts": "1700.1"}
        self._mock_channel_info(mock_slack)
        comment = self._comment()

        # A client-supplied channel_name must have no effect — the name is resolved from Slack.
        res = self._send(comment.id, extra={"channel_name": "#spoofed"})

        assert res.status_code == status.HTTP_200_OK, res.json()
        mirror = CommentSlackThread.objects.for_team(self.team.id).get()
        assert mirror.source_comment_id == comment.id
        assert mirror.slack_thread_ts == "1700.1"
        assert (mirror.slack_channel_id, mirror.slack_team_id) == ("C1", "T123")
        assert mirror.slack_channel_name == "team-support"
        assert res.json()["slack_channel_name"] == "team-support"
        # Only the root is posted synchronously; replies are backfilled out-of-band.
        assert mock_slack.return_value.client.chat_postMessage.call_count == 1
        mock_backfill.assert_called_once_with(comment_slack_thread_id=str(mirror.id))

    @patch("posthog.api.comments.backfill_comment_slack_thread.delay")
    @patch("posthog.api.comments.posthoganalytics.feature_enabled", return_value=True)
    @patch("posthog.api.comments.SlackIntegration")
    def test_idempotent_does_not_repost(self, mock_slack, _flag, _backfill):
        mock_slack.return_value.client.chat_postMessage.return_value = {"ts": "1700.1"}
        self._mock_channel_info(mock_slack)
        comment = self._comment()

        first = self._send(comment.id)
        second = self._send(comment.id)

        assert first.status_code == status.HTTP_200_OK
        assert second.status_code == status.HTTP_200_OK
        assert CommentSlackThread.objects.for_team(self.team.id).count() == 1
        assert mock_slack.return_value.client.chat_postMessage.call_count == 1

    @patch("posthog.api.comments.backfill_comment_slack_thread.delay")
    @patch("posthog.api.comments.posthoganalytics.feature_enabled", return_value=True)
    @patch("posthog.api.comments.SlackIntegration")
    def test_failed_post_releases_reservation(self, mock_slack, _flag, _backfill):
        mock_slack.return_value.client.chat_postMessage.side_effect = Exception("slack down")
        self._mock_channel_info(mock_slack)
        comment = self._comment()

        res = self._send(comment.id)

        assert res.status_code == status.HTTP_400_BAD_REQUEST
        # The reserved row is rolled back so a later attempt isn't blocked by the idempotency check.
        assert not CommentSlackThread.objects.for_team(self.team.id).exists()

    @patch("posthog.api.comments.posthoganalytics.feature_enabled", return_value=False)
    def test_404_when_flag_disabled(self, _flag):
        comment = self._comment()

        res = self._send(comment.id)

        assert res.status_code == status.HTTP_404_NOT_FOUND
        assert not CommentSlackThread.objects.for_team(self.team.id).exists()

    @patch("posthog.api.comments.backfill_comment_slack_thread.delay")
    @patch("posthog.api.comments.posthoganalytics.feature_enabled", return_value=True)
    @patch("posthog.api.comments.SlackIntegration")
    def test_resend_to_different_channel_names_existing_one(self, mock_slack, _flag, _backfill):
        mock_slack.return_value.client.chat_postMessage.return_value = {"ts": "1700.1"}
        self._mock_channel_info(mock_slack)
        comment = self._comment()
        self._send(comment.id, channel_id="C1")

        res = self._send(comment.id, channel_id="C2")

        assert res.status_code == status.HTTP_400_BAD_REQUEST
        assert "C1" in str(res.json())
        # No second root post, mapping unchanged.
        assert mock_slack.return_value.client.chat_postMessage.call_count == 1
        assert CommentSlackThread.objects.for_team(self.team.id).get().slack_channel_id == "C1"

    @patch("posthog.api.comments.backfill_comment_slack_thread.delay")
    @patch("posthog.api.comments.posthoganalytics.feature_enabled", return_value=True)
    @patch("posthog.api.comments.SlackIntegration")
    def test_in_flight_reservation_returns_409(self, mock_slack, _flag, _backfill):
        self._mock_channel_info(mock_slack)
        comment = self._comment()
        # A fresh reservation with no posted root — another request is mid-send.
        CommentSlackThread.objects.for_team(self.team.id).create(
            team=self.team,
            scope="Insight",
            item_id="42",
            source_comment=comment,
            integration=self.integration,
            slack_channel_id="C1",
        )

        res = self._send(comment.id)

        assert res.status_code == status.HTTP_409_CONFLICT
        mock_slack.return_value.client.chat_postMessage.assert_not_called()

    @patch("posthog.api.comments.backfill_comment_slack_thread.delay")
    @patch("posthog.api.comments.posthoganalytics.feature_enabled", return_value=True)
    @patch("posthog.api.comments.SlackIntegration")
    def test_stale_reservation_is_adopted_and_retried(self, mock_slack, _flag, mock_backfill):
        mock_slack.return_value.client.chat_postMessage.return_value = {"ts": "1700.9"}
        self._mock_channel_info(mock_slack)
        comment = self._comment()
        # A crashed send left an old reservation with no root message.
        stale = CommentSlackThread.objects.for_team(self.team.id).create(
            team=self.team,
            scope="Insight",
            item_id="42",
            source_comment=comment,
            integration=self.integration,
            slack_channel_id="C1",
        )
        CommentSlackThread.objects.for_team(self.team.id).filter(id=stale.id).update(
            created_at=timezone.now() - timedelta(minutes=10)
        )

        res = self._send(comment.id, channel_id="C2")

        assert res.status_code == status.HTTP_200_OK, res.json()
        mirror = CommentSlackThread.objects.for_team(self.team.id).get()
        assert (mirror.slack_thread_ts, mirror.slack_channel_id) == ("1700.9", "C2")
        mock_backfill.assert_called_once_with(comment_slack_thread_id=str(mirror.id))

    @parameterized.expand(
        [
            ("creator_sends_with_masked_name", True, status.HTTP_200_OK),
            ("non_creator_forbidden", False, status.HTTP_403_FORBIDDEN),
        ]
    )
    @patch("posthog.api.comments.backfill_comment_slack_thread.delay")
    @patch("posthog.api.comments.posthoganalytics.feature_enabled", return_value=True)
    @patch("posthog.api.comments.SlackIntegration")
    def test_private_channel_guard(self, _name, requester_is_creator, expected_status, mock_slack, _flag, _backfill):
        if requester_is_creator:
            self.integration.created_by = self.user
            self.integration.save()
        mock_slack.return_value.client.chat_postMessage.return_value = {"ts": "1700.1"}
        self._mock_channel_info(mock_slack, name="secret-plans", is_private=True)
        comment = self._comment()

        res = self._send(comment.id)

        assert res.status_code == expected_status, res.json()
        if requester_is_creator:
            mirror = CommentSlackThread.objects.for_team(self.team.id).get()
            # A private channel's name is never persisted — it would be shown to every reader.
            assert mirror.slack_channel_name == ""
            assert res.json()["slack_channel_name"] == ""
        else:
            assert not CommentSlackThread.objects.for_team(self.team.id).exists()
            mock_slack.return_value.client.chat_postMessage.assert_not_called()

    @patch("posthog.api.comments.backfill_comment_slack_thread.delay")
    @patch("posthog.api.comments.posthoganalytics.feature_enabled", return_value=True)
    @patch("posthog.api.comments.SlackIntegration")
    def test_channel_lookup_failure_is_a_400(self, mock_slack, _flag, _backfill):
        mock_slack.return_value.client.conversations_info.side_effect = SlackApiError(
            "boom", {"error": "channel_not_found"}
        )
        comment = self._comment()

        res = self._send(comment.id)

        assert res.status_code == status.HTTP_400_BAD_REQUEST
        assert "channel_not_found" in str(res.json())
        assert not CommentSlackThread.objects.for_team(self.team.id).exists()
        mock_slack.return_value.client.chat_postMessage.assert_not_called()

    @parameterized.expand([("reply", "source_comment"), ("unknown_integration", "integration")])
    @patch("posthog.api.comments.posthoganalytics.feature_enabled", return_value=True)
    def test_rejects_invalid_target(self, _name, bad, _flag):
        if bad == "source_comment":
            parent = self._comment()
            res = self._send(self._comment(source_comment=parent).id)
        else:
            res = self._send(self._comment().id, integration_id=999999)

        assert res.status_code == status.HTTP_400_BAD_REQUEST
        assert not CommentSlackThread.objects.for_team(self.team.id).exists()


class TestCommentReplySlackSignal(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.integration = Integration.objects.create(
            team=self.team, kind="slack", integration_id="T1", sensitive_config={"access_token": "t"}
        )
        self.parent = Comment.objects.create(team=self.team, scope="Insight", item_id="42", content="root")
        self.other_parent = Comment.objects.create(team=self.team, scope="Insight", item_id="99", content="root2")
        CommentSlackThread.objects.for_team(self.team.id).create(
            team=self.team,
            scope="Insight",
            item_id="42",
            source_comment=self.parent,
            integration=self.integration,
            slack_channel_id="C1",
            slack_thread_ts="1700.1",
        )

    @parameterized.expand(
        [
            ("mirrored_reply", "parent", "Insight", None, True),
            ("non_mirrored_reply", "other_parent", "Insight", None, False),
            ("from_slack_reply_not_echoed", "parent", "Insight", {"from_slack": True}, False),
            ("emoji_reaction_not_mirrored", "parent", "Insight", {"is_emoji": True}, False),
            ("conversations_ticket_excluded", "parent", "conversations_ticket", None, False),
            ("email_thread_excluded", "parent", "EmailThread", None, False),
            ("top_level_comment", None, "Insight", None, False),
        ]
    )
    @patch("posthog.tasks.comment_slack_sync.mirror_comment_reply_to_slack.delay")
    def test_reply_enqueues_only_when_it_should(
        self, _name, parent_attr, scope, item_context, expected_called, mock_delay
    ):
        source = getattr(self, parent_attr) if parent_attr else None
        # A valid-UUID item_id keeps the conversations product's own ticket signals (which parse
        # item_id as a Ticket UUID for the conversations_ticket scope) from choking on this case.
        item_id = "00000000-0000-0000-0000-000000000042"
        with self.captureOnCommitCallbacks(execute=True):
            Comment.objects.create(
                team=self.team,
                scope=scope,
                item_id=item_id,
                content="reply",
                source_comment=source,
                item_context=item_context,
                created_by=self.user,
            )

        assert mock_delay.called is expected_called


class TestReplyMirror(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.integration = Integration.objects.create(
            team=self.team, kind="slack", integration_id="T1", sensitive_config={"access_token": "t"}
        )
        self.parent = Comment.objects.create(team=self.team, scope="Insight", item_id="42", content="root")

    def _mirror(self) -> CommentSlackThread:
        return CommentSlackThread.objects.for_team(self.team.id).create(
            team=self.team,
            scope="Insight",
            item_id="42",
            source_comment=self.parent,
            integration=self.integration,
            slack_channel_id="C1",
            slack_thread_ts="100.1",
        )

    @patch("posthog.tasks.comment_slack_sync.SlackIntegration")
    def test_posts_reply_to_the_mirrored_thread(self, mock_slack):
        self._mirror()
        reply = Comment.objects.create(
            team=self.team, scope="Insight", item_id="42", content="reply", source_comment=self.parent
        )

        mirror_comment_reply_to_slack.apply(kwargs={"comment_id": str(reply.id)})

        client = mock_slack.return_value.client
        assert client.chat_postMessage.call_count == 1
        assert client.chat_postMessage.call_args.kwargs["thread_ts"] == "100.1"

    @patch("posthog.tasks.comment_slack_sync.SlackIntegration")
    def test_noop_when_thread_has_no_mirror(self, mock_slack):
        reply = Comment.objects.create(
            team=self.team, scope="Insight", item_id="42", content="reply", source_comment=self.parent
        )

        mirror_comment_reply_to_slack.apply(kwargs={"comment_id": str(reply.id)})

        mock_slack.assert_not_called()

    @patch("posthog.tasks.comment_slack_sync.SlackIntegration")
    def test_email_thread_reply_is_not_mirrored(self, mock_slack):
        parent = Comment.objects.create(team=self.team, scope="EmailThread", item_id="thread-42", content="root")
        CommentSlackThread.objects.for_team(self.team.id).create(
            team=self.team,
            scope="EmailThread",
            item_id="thread-42",
            source_comment=parent,
            integration=self.integration,
            slack_channel_id="C1",
            slack_thread_ts="100.1",
        )
        reply = Comment.objects.create(
            team=self.team,
            scope="EmailThread",
            item_id="thread-42",
            content="reply",
            source_comment=parent,
        )

        mirror_comment_reply_to_slack.apply(kwargs={"comment_id": str(reply.id)})

        mock_slack.assert_not_called()

    @patch("posthog.tasks.comment_slack_sync.SlackIntegration")
    def test_reply_posts_once_across_task_reruns(self, mock_slack):
        mock_slack.return_value.client.chat_postMessage.return_value = {"ts": "100.2"}
        self._mirror()
        reply = Comment.objects.create(
            team=self.team, scope="Insight", item_id="42", content="reply", source_comment=self.parent
        )

        # A Celery retry after a successful post re-runs the whole task; the synced marker
        # stamped on the first run must prevent a duplicate Slack message.
        mirror_comment_reply_to_slack.apply(kwargs={"comment_id": str(reply.id)})
        mirror_comment_reply_to_slack.apply(kwargs={"comment_id": str(reply.id)})

        assert mock_slack.return_value.client.chat_postMessage.call_count == 1
        reply.refresh_from_db()
        assert reply.item_context is not None
        assert reply.item_context[SLACK_SYNCED_TS_KEY] == "100.2"

    @patch("posthog.tasks.comment_slack_sync.SlackIntegration")
    def test_reply_retries_while_root_post_pending(self, mock_slack):
        # Reservation exists but the root hasn't posted yet (send_to_slack mid-flight):
        # the reply must be retried, not dropped and not posted out of order.
        mirror = self._mirror()
        CommentSlackThread.objects.for_team(self.team.id).filter(id=mirror.id).update(slack_thread_ts="")
        reply = Comment.objects.create(
            team=self.team, scope="Insight", item_id="42", content="reply", source_comment=self.parent
        )

        with self.assertRaises(Retry):
            mirror_comment_reply_to_slack(comment_id=str(reply.id))

        mock_slack.return_value.client.chat_postMessage.assert_not_called()

    @patch("posthog.tasks.comment_slack_sync.posthoganalytics.feature_enabled", return_value=False)
    @patch("posthog.tasks.comment_slack_sync.SlackIntegration")
    def test_kill_switch_stops_reply_sync(self, mock_slack, _flag):
        self._mirror()
        reply = Comment.objects.create(
            team=self.team, scope="Insight", item_id="42", content="reply", source_comment=self.parent
        )

        mirror_comment_reply_to_slack.apply(kwargs={"comment_id": str(reply.id)})

        mock_slack.assert_not_called()


class TestBackfill(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.integration = Integration.objects.create(
            team=self.team, kind="slack", integration_id="T1", sensitive_config={"access_token": "t"}
        )
        self.parent = Comment.objects.create(team=self.team, scope="Insight", item_id="42", content="root")

    def _reply(self, content: str, **kwargs) -> Comment:
        return Comment.objects.create(
            team=self.team, scope="Insight", item_id="42", content=content, source_comment=self.parent, **kwargs
        )

    def _mirror(self) -> CommentSlackThread:
        # Matches the real flow: replies exist first, then send_to_slack creates the mirror.
        return CommentSlackThread.objects.for_team(self.team.id).create(
            team=self.team,
            scope="Insight",
            item_id="42",
            source_comment=self.parent,
            integration=self.integration,
            slack_channel_id="C1",
            slack_thread_ts="100.1",
        )

    @patch("posthog.tasks.comment_slack_sync.SlackIntegration")
    def test_backfills_replies_and_skips_from_slack_and_emoji(self, mock_slack):
        mock_slack.return_value.client.chat_postMessage.return_value = {"ts": "100.2"}
        self._reply("r1")
        self._reply("r2")
        # A reply that came in from Slack must not be echoed back; reactions aren't messages.
        self._reply("from slack", item_context={"from_slack": True})
        self._reply("👍", item_context={"is_emoji": True})
        mirror = self._mirror()

        backfill_comment_slack_thread(str(mirror.id))

        # r1 + r2 only — from_slack and emoji replies are skipped, and the root isn't a reply.
        assert mock_slack.return_value.client.chat_postMessage.call_count == 2

    @patch("posthog.tasks.comment_slack_sync.time.sleep")
    @patch("posthog.tasks.comment_slack_sync.SlackIntegration")
    def test_backfill_retries_once_after_slack_rate_limit(self, mock_slack, mock_sleep):
        rate_limited = MagicMock()
        rate_limited.get.side_effect = lambda key, default=None: {"error": "ratelimited"}.get(key, default)
        rate_limited.headers = {"Retry-After": "2"}
        mock_slack.return_value.client.chat_postMessage.side_effect = [
            SlackApiError("ratelimited", rate_limited),
            {"ts": "100.2"},
        ]
        reply = self._reply("r1")
        mirror = self._mirror()

        backfill_comment_slack_thread(str(mirror.id))

        # The rate-limited post is retried after Slack's Retry-After instead of dropping the reply.
        assert mock_slack.return_value.client.chat_postMessage.call_count == 2
        mock_sleep.assert_called_once_with(2)
        reply.refresh_from_db()
        assert reply.item_context is not None
        assert reply.item_context[SLACK_SYNCED_TS_KEY] == "100.2"

    @patch("posthog.tasks.comment_slack_sync.SlackIntegration")
    def test_backfill_owns_only_replies_that_predate_the_mirror(self, mock_slack):
        mock_slack.return_value.client.chat_postMessage.return_value = {"ts": "100.2"}
        self._reply("before")
        mirror = self._mirror()
        # Created after the mirror: the live post_save signal owns it — backfill posting it
        # too is the double-post race.
        self._reply("after")

        backfill_comment_slack_thread(str(mirror.id))

        assert mock_slack.return_value.client.chat_postMessage.call_count == 1

    @patch("posthog.tasks.comment_slack_sync.SlackIntegration")
    def test_backfill_rerun_does_not_double_post(self, mock_slack):
        mock_slack.return_value.client.chat_postMessage.return_value = {"ts": "100.2"}
        self._reply("r1")
        mirror = self._mirror()

        backfill_comment_slack_thread(str(mirror.id))
        backfill_comment_slack_thread(str(mirror.id))

        assert mock_slack.return_value.client.chat_postMessage.call_count == 1

    @patch("posthog.tasks.comment_slack_sync.backfill_comment_slack_thread.apply_async")
    @patch("posthog.tasks.comment_slack_sync.SlackIntegration")
    def test_backfill_stops_at_the_batch_size_and_reschedules(self, mock_slack, mock_apply_async):
        # Reply history is caller-controlled, so one run must not walk an unbounded thread while
        # holding a shared worker.
        mock_slack.return_value.client.chat_postMessage.return_value = {"ts": "100.2"}
        for index in range(BACKFILL_BATCH_SIZE + 3):
            self._reply(f"r{index}")
        mirror = self._mirror()

        backfill_comment_slack_thread(str(mirror.id))

        assert mock_slack.return_value.client.chat_postMessage.call_count == BACKFILL_BATCH_SIZE
        mock_apply_async.assert_called_once_with((str(mirror.id),), countdown=BACKFILL_RESCHEDULE_COUNTDOWN_SECONDS)

    @patch("posthog.tasks.comment_slack_sync.backfill_comment_slack_thread.apply_async")
    @patch("posthog.tasks.comment_slack_sync.SlackIntegration")
    def test_backfill_does_not_reschedule_when_the_batch_posted_nothing(self, mock_slack, mock_apply_async):
        # A failed post leaves the reply unstamped, so it stays in the next batch — rescheduling on
        # "work remains" alone would requeue the same doomed batch forever.
        mock_slack.return_value.client.chat_postMessage.side_effect = Exception("slack is down")
        for index in range(BACKFILL_BATCH_SIZE + 3):
            self._reply(f"r{index}")
        mirror = self._mirror()

        backfill_comment_slack_thread(str(mirror.id))

        mock_apply_async.assert_not_called()


class TestSlackThreadSerialization(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.integration = Integration.objects.create(
            team=self.team, kind="slack", integration_id="T1", sensitive_config={"access_token": "t"}
        )
        self.parent = Comment.objects.create(team=self.team, scope="Insight", item_id="42", content="root")
        self.mirror = CommentSlackThread.objects.for_team(self.team.id).create(
            team=self.team,
            scope="Insight",
            item_id="42",
            source_comment=self.parent,
            integration=self.integration,
            slack_channel_id="C1",
            slack_channel_name="team-support",
            slack_thread_ts="1700.1",
        )

    @patch("posthog.api.comments.posthoganalytics.feature_enabled", return_value=True)
    def test_detail_response_includes_slack_thread(self, _mock_flag):
        # Detail responses replace list entries client-side — dropping slack_thread there
        # made the "Open in Slack" state vanish after an edit/complete.
        res = self.client.get(f"/api/projects/{self.team.id}/comments/{self.parent.id}/")

        assert res.status_code == status.HTTP_200_OK
        assert res.json()["slack_thread"] == {
            "channel_id": "C1",
            "channel_name": "team-support",
            "url": "https://app.slack.com/archives/C1/p17001",
        }

    @patch("posthog.api.comments.posthoganalytics.feature_enabled", return_value=True)
    def test_unposted_reservation_serializes_as_null(self, _mock_flag):
        # A reservation with no root message isn't a live mirror; reporting it would show a
        # dead "Open in Slack" link and hide re-sending.
        CommentSlackThread.objects.for_team(self.team.id).filter(id=self.mirror.id).update(slack_thread_ts="")

        res = self.client.get(f"/api/projects/{self.team.id}/comments/?scope=Insight&item_id=42")

        assert res.status_code == status.HTTP_200_OK
        results = {r["id"]: r for r in res.json()["results"]}
        assert results[str(self.parent.id)]["slack_thread"] is None

    @patch("posthog.api.comments.posthoganalytics.feature_enabled", return_value=True)
    def test_canvas_mirror_is_found_under_either_scope_name(self, _mock_flag):
        channel = (
            apps.get_model("tasks", "Channel")
            .objects.unscoped()
            .create(team=self.team, name="mirror-space", channel_type="public", created_by=self.user)
        )
        canvas_id = canvas_testing.create_canvas(
            team_id=self.team.id, channel_id=channel.id, name="Mirrored canvas", created_by_id=self.user.id
        )
        root = Comment.objects.create(team=self.team, scope="desktop_canvas", item_id=str(canvas_id), content="root")
        CommentSlackThread.objects.for_team(self.team.id).create(
            team=self.team,
            scope="canvas",
            item_id=str(canvas_id),
            source_comment=root,
            integration=self.integration,
            slack_channel_id="C2",
            slack_channel_name="canvas-feedback",
            slack_thread_ts="1700.2",
        )

        res = self.client.get(f"/api/projects/{self.team.id}/comments/?scope=canvas&item_id={canvas_id}")

        assert res.status_code == status.HTTP_200_OK
        results = {r["id"]: r for r in res.json()["results"]}
        assert results[str(root.id)]["slack_thread"]["channel_id"] == "C2"

    def test_slack_thread_lookup_skipped_when_flag_off(self):
        # Unflagged teams must not pay the mirror lookup on the hot comments endpoint.
        with patch("posthog.api.comments.posthoganalytics.feature_enabled", return_value=False):
            res = self.client.get(f"/api/projects/{self.team.id}/comments/{self.parent.id}/")
        assert res.status_code == status.HTTP_200_OK
        assert res.json()["slack_thread"] is None


ROOT_TS = "1767225636.295669"
REPLY_TS = "1767225999.000100"
CHANNEL = "C0123ABCDEF"
ROOT_LINK = f"https://posthog.slack.com/archives/{CHANNEL}/p1767225636295669"
REPLY_LINK = f"https://posthog.slack.com/archives/{CHANNEL}/p1767225999000100"
ROOT_MESSAGE = {"ts": ROOT_TS, "user": "U1", "text": "has anyone seen exports stall like this?"}


def _thread_page(*messages: dict) -> dict:
    return {"messages": list(messages), "has_more": False}


def _slack_error(code: str) -> SlackApiError:
    return SlackApiError(code, MagicMock(get=lambda key, default=None: code if key == "error" else default))


class TestLinkSlackThread(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.integration = Integration.objects.create(
            team=self.team,
            kind="slack",
            integration_id="T123",
            config={"authed_user": {"id": "u"}},
            sensitive_config={"access_token": "xoxb-test"},
        )
        self.ticket = Ticket.objects.create_with_number(
            team=self.team,
            channel_source=Channel.WIDGET,
            widget_session_id="link-session",
            distinct_id="link-user",
            status=Status.OPEN,
        )
        self.slack_profile = {
            "name": "Ada",
            "email": self.user.email,
            "avatar": "https://avatars.slack-edu.com/ada_72.png",
            "team_id": "T123",
        }

    def _link(self, url: str = ROOT_LINK, **overrides):
        return self.client.post(
            f"/api/projects/{self.team.id}/comments/link_slack_thread/",
            {
                "scope": "Ticket",
                "item_id": str(self.ticket.id),
                "integration_id": self.integration.id,
                "url": url,
                **overrides,
            },
            format="json",
        )

    def _mock_slack(self, mock_slack, *pages) -> MagicMock:
        client = mock_slack.return_value.client
        client.conversations_info.return_value = {
            "channel": {"id": CHANNEL, "name": "support-escalations", "is_channel": True, "is_private": False}
        }
        client.conversations_replies.side_effect = list(pages)
        client.users_lookupByEmail.return_value = {"user": {"id": "U9", "team_id": "T123"}}
        return client

    @parameterized.expand(
        [
            ("root_link", ROOT_LINK, [_thread_page(ROOT_MESSAGE)]),
            (
                "reply_link_naming_its_thread",
                f"{REPLY_LINK}?thread_ts={ROOT_TS}&cid={CHANNEL}",
                [_thread_page(ROOT_MESSAGE)],
            ),
            (
                "reply_link_without_its_thread",
                REPLY_LINK,
                [
                    _thread_page({"ts": REPLY_TS, "thread_ts": ROOT_TS, "user": "U2", "text": "yup"}),
                    _thread_page(ROOT_MESSAGE),
                ],
            ),
        ]
    )
    @patch("posthog.tasks.comment_slack_sync.import_linked_slack_thread.delay")
    @patch("posthog.api.comments.resolve_slack_user")
    @patch("posthog.api.comments.posthoganalytics.feature_enabled", return_value=True)
    @patch("posthog.api.comments.SlackIntegration")
    def test_links_the_thread_the_message_is_in(self, _name, url, pages, mock_slack, _flag, mock_profile, mock_import):
        mock_profile.return_value = self.slack_profile
        client = self._mock_slack(mock_slack, *pages)

        with self.captureOnCommitCallbacks(execute=True):
            res = self._link(url)

        assert res.status_code == status.HTTP_201_CREATED, res.json()
        body = res.json()
        assert body["content"] == ROOT_MESSAGE["text"]
        assert body["created_by"]["id"] == self.user.id
        assert body["item_context"]["slack_author_name"] == "Ada"
        # Placed where the conversation started in Slack, not when it was linked.
        assert Comment.objects.get(id=body["id"]).created_at.isoformat() == "2026-01-01T00:00:36.295669+00:00"
        assert body["slack_thread"] == {
            "channel_id": CHANNEL,
            "channel_name": "support-escalations",
            "url": f"https://app.slack.com/archives/{CHANNEL}/p1767225636295669",
        }
        assert body["item_context"]["slack_import_state"] == "pending"
        mirror = CommentSlackThread.objects.for_team(self.team.id).get()
        assert (str(mirror.source_comment_id), mirror.slack_thread_ts) == (body["id"], ROOT_TS)
        mock_import.assert_called_once_with(comment_slack_thread_id=str(mirror.id))
        client.chat_postMessage.assert_not_called()

    @patch("posthog.tasks.comment_slack_sync.import_linked_slack_thread.delay")
    @patch("posthog.api.comments.posthoganalytics.feature_enabled", return_value=True)
    @patch("posthog.api.comments.SlackIntegration")
    def test_credits_a_thread_an_app_started_to_that_app(self, mock_slack, _flag, _import):
        alert = {"ts": ROOT_TS, "bot_id": "B1", "bot_profile": {"name": "incident.io"}, "text": "INC-123 opened"}
        self._mock_slack(mock_slack, _thread_page(alert))

        res = self._link()

        assert res.status_code == status.HTTP_201_CREATED, res.json()
        assert res.json()["created_by"] is None
        assert res.json()["item_context"]["slack_author_name"] == "incident.io"

    @patch("posthog.tasks.comment_slack_sync.import_linked_slack_thread.delay")
    @patch("posthog.api.comments.resolve_slack_user")
    @patch("posthog.api.comments.posthoganalytics.feature_enabled", return_value=True)
    @patch("posthog.api.comments.SlackIntegration")
    def test_refuses_a_thread_that_already_syncs_anywhere_on_the_workspace(
        self, mock_slack, _flag, mock_profile, _import
    ):
        # Inbound replies reach only one mirror, so a second link would silently get none.
        mock_profile.return_value = self.slack_profile
        self._mock_slack(mock_slack, _thread_page(ROOT_MESSAGE))
        other_team = Team.objects.create(organization=self.organization, name="Other project")
        other_integration = Integration.objects.create(
            team=other_team, kind="slack", integration_id="T123", sensitive_config={"access_token": "t"}
        )
        other_root = Comment.objects.create(team=other_team, scope="Insight", item_id="1", content="root")
        CommentSlackThread.objects.for_team(other_team.id).create(
            team=other_team,
            scope="Insight",
            item_id="1",
            source_comment=other_root,
            integration=other_integration,
            slack_channel_id=CHANNEL,
            slack_thread_ts=ROOT_TS,
            slack_team_id="T123",
        )

        res = self._link()

        assert res.status_code == status.HTTP_400_BAD_REQUEST
        assert "already syncs" in str(res.json())
        assert not Comment.objects.filter(team=self.team, scope="Ticket").exists()

    @parameterized.expand(
        [
            ("not_a_slack_link", "https://example.com/archives/C1/p1767225636295669", None, "Copy link"),
            ("bot_not_in_channel", ROOT_LINK, "not_in_channel", "isn't in that channel"),
            ("message_deleted", ROOT_LINK, "thread_not_found", "Couldn't find that Slack message"),
        ]
    )
    @patch("posthog.api.comments.posthoganalytics.feature_enabled", return_value=True)
    @patch("posthog.api.comments.SlackIntegration")
    def test_explains_a_link_it_cannot_follow(self, _name, url, slack_error, expected, mock_slack, _flag):
        client = self._mock_slack(mock_slack)
        if slack_error:
            client.conversations_replies.side_effect = _slack_error(slack_error)

        res = self._link(url)

        assert res.status_code == status.HTTP_400_BAD_REQUEST
        assert expected in str(res.json())
        assert not CommentSlackThread.objects.for_team(self.team.id).exists()
        assert not Comment.objects.filter(team=self.team, scope="Ticket").exists()

    # Replies on the discussion are posted back into the linked thread, so a channel anyone outside
    # the workspace can read would receive internal discussion.
    @parameterized.expand(
        [
            ("slack_connect", {"is_ext_shared": True, "is_shared": True}),
            ("pending_slack_connect_invite", {"is_pending_ext_shared": True}),
            ("shared_across_an_enterprise_org", {"is_org_shared": True}),
            ("payload_that_does_not_say_it_is_a_channel", {"is_channel": False}),
        ]
    )
    @patch("posthog.api.comments.posthoganalytics.feature_enabled", return_value=True)
    @patch("posthog.api.comments.SlackIntegration")
    def test_refuses_a_channel_that_is_not_internal(self, _name, flags, mock_slack, _flag):
        client = self._mock_slack(mock_slack, _thread_page(ROOT_MESSAGE))
        client.conversations_info.return_value["channel"].update(flags)

        res = self._link()

        assert res.status_code == status.HTTP_400_BAD_REQUEST
        assert "Only threads in internal channels can be linked" in str(res.json())
        client.conversations_replies.assert_not_called()
        assert not CommentSlackThread.objects.for_team(self.team.id).exists()

    # Linking it would post internal discussion replies to the customer. A ticket in another project of
    # the org, a deleted one and a purged one all still own their thread.
    @parameterized.expand([("this_project",), ("another_project_in_the_org",), ("deleted_ticket",), ("purged_ticket",)])
    @patch("posthog.tasks.comment_slack_sync.import_linked_slack_thread.delay")
    @patch("posthog.api.comments.resolve_slack_user")
    @patch("posthog.api.comments.posthoganalytics.feature_enabled", return_value=True)
    @patch("posthog.api.comments.SlackIntegration")
    def test_refuses_the_thread_a_support_ticket_talks_to_its_customer_in(
        self, case, mock_slack, _flag, mock_profile, _import
    ):
        mock_profile.return_value = self.slack_profile
        self._mock_slack(mock_slack, _thread_page(ROOT_MESSAGE))
        owner = (
            Team.objects.create(organization=self.organization, name="Support project")
            if case == "another_project_in_the_org"
            else self.team
        )
        if case == "purged_ticket":
            PurgedTicketThread.objects.for_team(owner.id).create(
                team=owner, thread_key=ticket_thread_key(slack_channel_id=CHANNEL, slack_thread_ts=ROOT_TS)
            )
        else:
            ticket = Ticket.objects.create_with_number(
                team=owner,
                channel_source=Channel.SLACK,
                slack_channel_id=CHANNEL,
                slack_thread_ts=ROOT_TS,
                status=Status.OPEN,
            )
            if case == "deleted_ticket":
                Ticket.all_objects.filter(id=ticket.id).update(deleted_at=timezone.now())

        res = self._link()

        assert res.status_code == status.HTTP_400_BAD_REQUEST
        assert "support ticket's conversation with the customer" in str(res.json())
        assert not CommentSlackThread.objects.for_team(self.team.id).exists()

    @patch("posthog.api.comments.slack_thread_has_agent_task", return_value=True)
    @patch("posthog.api.comments.resolve_slack_user")
    @patch("posthog.api.comments.posthoganalytics.feature_enabled", return_value=True)
    @patch("posthog.api.comments.SlackIntegration")
    def test_refuses_a_thread_the_agent_is_working_in(self, mock_slack, _flag, mock_profile, mock_agent):
        # The agent receives the thread's replies, so the discussion would never get one.
        mock_profile.return_value = self.slack_profile
        self._mock_slack(mock_slack, _thread_page(ROOT_MESSAGE))

        res = self._link()

        assert res.status_code == status.HTTP_400_BAD_REQUEST
        assert "agent is working in that thread" in str(res.json())
        mock_agent.assert_called_once_with(slack_workspace_id="T123", channel=CHANNEL, thread_ts=ROOT_TS)
        assert not CommentSlackThread.objects.for_team(self.team.id).exists()

    # Linking reads the thread with the bot's access, so only someone who could read it in Slack may link it.
    @parameterized.expand(
        [
            ("no_member_with_that_email", _slack_error("users_not_found"), "no member there uses"),
            ("guest", {"user": {"team_id": "T123", "is_restricted": True}}, "Guests"),
            ("single_channel_guest", {"user": {"team_id": "T123", "is_ultra_restricted": True}}, "Guests"),
            ("member_of_another_workspace", {"user": {"team_id": "T999"}}, "other workspaces"),
        ]
    )
    @patch("posthog.api.comments.posthoganalytics.feature_enabled", return_value=True)
    @patch("posthog.api.comments.SlackIntegration")
    def test_refuses_someone_who_is_not_a_full_member_of_the_workspace(
        self, _name, lookup, expected, mock_slack, _flag
    ):
        client = self._mock_slack(mock_slack, _thread_page(ROOT_MESSAGE))
        if isinstance(lookup, Exception):
            client.users_lookupByEmail.side_effect = lookup
        else:
            client.users_lookupByEmail.return_value = lookup

        res = self._link()

        assert res.status_code == status.HTTP_403_FORBIDDEN
        assert expected in str(res.json())
        client.conversations_replies.assert_not_called()

    @parameterized.expand(
        [
            # slack_sdk raises these, not SlackApiError, when Slack is slow or the connection drops.
            ("thread_read_times_out", "conversations_replies", TimeoutError("read timed out")),
            ("channel_lookup_times_out", "conversations_info", TimeoutError("read timed out")),
        ]
    )
    @patch("posthog.api.comments.posthoganalytics.feature_enabled", return_value=True)
    @patch("posthog.api.comments.SlackIntegration")
    def test_a_slack_timeout_is_a_503_not_a_500(self, _name, method, error, mock_slack, _flag):
        client = self._mock_slack(mock_slack, _thread_page(ROOT_MESSAGE))
        getattr(client, method).side_effect = error

        res = self._link()

        assert res.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        assert not CommentSlackThread.objects.for_team(self.team.id).exists()

    @patch("posthog.api.comments.resolve_slack_user")
    @patch("posthog.api.comments.posthoganalytics.feature_enabled", return_value=True)
    @patch("posthog.api.comments.SlackIntegration")
    def test_an_unresolved_thread_author_is_retryable_not_saved_as_unknown(self, mock_slack, _flag, mock_profile):
        # Saved now, the discussion would read "Started by Unknown" for good.
        mock_profile.return_value = {"name": "Unknown", "email": None, "avatar": None, "team_id": None}
        self._mock_slack(mock_slack, _thread_page(ROOT_MESSAGE))

        res = self._link()

        assert res.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        assert not Comment.objects.filter(team=self.team, scope="Ticket").exists()

    # A deleted discussion must free its thread, whether it was deleted on its own or in bulk.
    @parameterized.expand([("deleted_on_its_own",), ("deleted_in_bulk",)])
    @patch("posthog.tasks.comment_slack_sync.import_linked_slack_thread.delay")
    @patch("posthog.api.comments.resolve_slack_user")
    @patch("posthog.api.comments.posthoganalytics.feature_enabled", return_value=True)
    @patch("posthog.api.comments.SlackIntegration")
    def test_a_thread_can_be_linked_again_once_its_discussion_is_deleted(
        self, how, mock_slack, _flag, mock_profile, _import
    ):
        mock_profile.return_value = self.slack_profile
        self._mock_slack(mock_slack, _thread_page(ROOT_MESSAGE), _thread_page(ROOT_MESSAGE))
        first = self._link()
        assert first.status_code == status.HTTP_201_CREATED, first.json()
        root = Comment.objects.get(id=first.json()["id"])
        if how == "deleted_on_its_own":
            root.deleted = True
            root.save()
        else:
            Comment.objects.filter(id=root.id).update(deleted=True)
        # Deleted on its own, the discussion stops syncing at once. A bulk delete skips signals, so its
        # thread is only released by the next link.
        assert CommentSlackThread.objects.for_team(self.team.id).exists() == (how == "deleted_in_bulk")

        second = self._link()

        assert second.status_code == status.HTTP_201_CREATED, second.json()
        assert CommentSlackThread.objects.for_team(self.team.id).get().source_comment_id == UUID(second.json()["id"])

    @patch("posthog.tasks.comment_slack_sync.import_linked_slack_thread.delay")
    @patch("posthog.api.comments.resolve_slack_user")
    @patch("posthog.api.comments.posthoganalytics.feature_enabled", return_value=True)
    @patch("posthog.api.comments.SlackIntegration")
    def test_unlinking_removes_the_discussion_and_frees_the_thread(self, mock_slack, _flag, mock_profile, _import):
        # The way back from a thread linked to the wrong ticket. The opening comment is credited to the
        # Slack author, so the person who linked it couldn't delete it themselves.
        mock_profile.return_value = {**self.slack_profile, "email": "ada@example.com"}
        self._mock_slack(mock_slack, _thread_page(ROOT_MESSAGE), _thread_page(ROOT_MESSAGE))
        root_id = self._link().json()["id"]
        reply = Comment.objects.create(
            team=self.team,
            scope="Ticket",
            item_id=str(self.ticket.id),
            source_comment_id=root_id,
            content="Thanks, taking a look",
            item_context={"from_slack": True, "slack_message_ts": REPLY_TS},
        )

        res = self.client.post(f"/api/projects/{self.team.id}/comments/{root_id}/unlink_slack_thread/")

        assert res.status_code == status.HTTP_204_NO_CONTENT
        assert set(Comment.objects.filter(id__in=[root_id, reply.id]).values_list("deleted", flat=True)) == {True}
        assert not CommentSlackThread.objects.for_team(self.team.id).exists()
        assert self._link().status_code == status.HTTP_201_CREATED

    # The bot can be in private channels the person who connected the workspace isn't in. Linking reads
    # the history with the bot's access, so the requester must be able to read it in Slack too.
    @parameterized.expand([("member_of_the_channel", True), ("not_in_the_channel", False)])
    @patch("posthog.tasks.comment_slack_sync.import_linked_slack_thread.delay")
    @patch("posthog.api.comments.resolve_slack_user")
    @patch("posthog.api.comments.posthoganalytics.feature_enabled", return_value=True)
    @patch("posthog.api.comments.SlackIntegration")
    def test_links_a_private_channel_thread_only_for_someone_in_it(
        self, _name, in_channel, mock_slack, _flag, mock_profile, _import
    ):
        mock_profile.return_value = self.slack_profile
        Integration.objects.filter(id=self.integration.id).update(created_by=self.user)
        client = self._mock_slack(mock_slack, _thread_page(ROOT_MESSAGE))
        client.conversations_info.return_value["channel"].update({"is_private": True, "is_group": True})
        client.conversations_members.return_value = {"members": ["U1", "U9"] if in_channel else ["U1"]}

        res = self._link()

        assert res.status_code == (status.HTTP_201_CREATED if in_channel else status.HTTP_403_FORBIDDEN), res.json()
        client.conversations_members.assert_called_once()
        assert CommentSlackThread.objects.for_team(self.team.id).exists() == in_channel
        if not in_channel:
            assert "aren't in that private channel" in str(res.json())
            client.conversations_replies.assert_not_called()

    @patch("posthog.tasks.comment_slack_sync.import_linked_slack_thread.delay", side_effect=ConnectionError("down"))
    @patch("posthog.api.comments.resolve_slack_user")
    @patch("posthog.api.comments.posthoganalytics.feature_enabled", return_value=True)
    @patch("posthog.api.comments.SlackIntegration")
    def test_a_link_whose_import_cannot_be_queued_says_the_import_failed(self, mock_slack, _flag, mock_profile, _):
        # The link has committed, so it stands. Left at "pending", the root would wait for history that
        # never comes; "failed" tells the person to unlink and link it again.
        mock_profile.return_value = self.slack_profile
        self._mock_slack(mock_slack, _thread_page(ROOT_MESSAGE))

        with self.captureOnCommitCallbacks(execute=True):
            res = self._link()

        assert res.status_code == status.HTTP_201_CREATED, res.json()
        root = Comment.objects.get(id=res.json()["id"])
        assert (root.item_context or {})["slack_import_state"] == "failed"

    @patch("posthog.tasks.comment_slack_sync.import_linked_slack_thread.delay")
    @patch("posthog.api.comments.resolve_slack_user")
    @patch("posthog.api.comments.posthoganalytics.feature_enabled", return_value=True)
    @patch("posthog.api.comments.SlackIntegration")
    def test_editing_the_opening_comment_keeps_what_marks_it_linked(self, mock_slack, _flag, mock_profile, _import):
        # The outbound checks on a linked thread key off from_slack. Dropping it on an edit would let
        # replies through to a channel that has since been shared outside the workspace.
        mock_profile.return_value = self.slack_profile
        self._mock_slack(mock_slack, _thread_page(ROOT_MESSAGE))
        root_id = self._link().json()["id"]

        res = self.client.patch(
            f"/api/projects/{self.team.id}/comments/{root_id}/",
            {"content": "edited", "item_context": {}},
            format="json",
        )

        assert res.status_code == status.HTTP_200_OK, res.json()
        context = Comment.objects.get(id=root_id).item_context or {}
        assert (context.get("from_slack"), context.get("slack_import_state")) == (True, "pending")

    @patch("posthog.tasks.comment_slack_sync.import_linked_slack_thread.delay")
    @patch("posthog.api.comments.resolve_slack_user")
    @patch("posthog.api.comments.posthoganalytics.feature_enabled", return_value=True)
    @patch("posthog.api.comments.SlackIntegration")
    def test_unlinking_needs_the_same_slack_membership_as_linking(self, mock_slack, _flag, mock_profile, _import):
        mock_profile.return_value = self.slack_profile
        client = self._mock_slack(mock_slack, _thread_page(ROOT_MESSAGE))
        root_id = self._link().json()["id"]
        client.users_lookupByEmail.return_value = {"user": {"team_id": "T123", "is_restricted": True}}

        res = self.client.post(f"/api/projects/{self.team.id}/comments/{root_id}/unlink_slack_thread/")

        assert res.status_code == status.HTTP_403_FORBIDDEN
        assert CommentSlackThread.objects.for_team(self.team.id).exists()

    @patch("posthog.tasks.comment_slack_sync.import_linked_slack_thread.delay")
    @patch("posthog.api.comments.resolve_slack_user")
    @patch("posthog.api.comments.posthoganalytics.feature_enabled", return_value=True)
    @patch("posthog.api.comments.SlackIntegration")
    def test_unlinking_waits_for_replies_still_on_their_way_to_slack(self, mock_slack, _flag, mock_profile, _import):
        # Unlinking deletes the discussion because the thread keeps a copy. This reply has no copy yet.
        mock_profile.return_value = self.slack_profile
        self._mock_slack(mock_slack, _thread_page(ROOT_MESSAGE))
        root_id = self._link().json()["id"]
        with patch("posthog.tasks.comment_slack_sync.mirror_comment_reply_to_slack.delay"):
            pending = Comment.objects.create(
                team=self.team, scope="Ticket", item_id=str(self.ticket.id), source_comment_id=root_id, content="hm"
            )

        refused = self.client.post(f"/api/projects/{self.team.id}/comments/{root_id}/unlink_slack_thread/")

        assert refused.status_code == status.HTTP_400_BAD_REQUEST
        assert "haven't reached the Slack thread yet" in str(refused.json())
        assert not Comment.objects.get(id=pending.id).deleted

        Comment.objects.filter(id=pending.id).update(item_context={"slack_synced_ts": "1767225900.000001"})
        res = self.client.post(f"/api/projects/{self.team.id}/comments/{root_id}/unlink_slack_thread/")
        assert res.status_code == status.HTTP_204_NO_CONTENT

    @patch("posthog.tasks.comment_slack_sync.import_linked_slack_thread.delay")
    @patch("posthog.api.comments.resolve_slack_user")
    @patch("posthog.api.comments.posthoganalytics.feature_enabled", return_value=True)
    @patch("posthog.api.comments.SlackIntegration")
    def test_unlinking_isnt_held_up_by_a_reply_that_will_never_reach_slack(
        self, mock_slack, _flag, mock_profile, _import
    ):
        # Refused after the channel was shared, or out of retries: it isn't on its way, and the person
        # unlinking may not be able to delete a teammate's reply to clear it.
        mock_profile.return_value = self.slack_profile
        self._mock_slack(mock_slack, _thread_page(ROOT_MESSAGE))
        root_id = self._link().json()["id"]
        with patch("posthog.tasks.comment_slack_sync.mirror_comment_reply_to_slack.delay"):
            stuck = Comment.objects.create(
                team=self.team, scope="Ticket", item_id=str(self.ticket.id), source_comment_id=root_id, content="hm"
            )
        Comment.objects.filter(id=stuck.id).update(created_at=timezone.now() - timedelta(hours=1))

        res = self.client.post(f"/api/projects/{self.team.id}/comments/{root_id}/unlink_slack_thread/")

        assert res.status_code == status.HTTP_204_NO_CONTENT

    @patch("posthog.tasks.comment_slack_sync.import_linked_slack_thread.delay")
    @patch("posthog.api.comments.resolve_slack_user")
    @patch("posthog.api.comments.posthoganalytics.feature_enabled", return_value=True)
    @patch("posthog.api.comments.SlackIntegration")
    def test_unlinking_still_works_once_the_slack_integration_is_gone(self, mock_slack, _flag, mock_profile, _import):
        # Nothing syncs without the integration, so the discussion can still be cleared away.
        mock_profile.return_value = self.slack_profile
        client = self._mock_slack(mock_slack, _thread_page(ROOT_MESSAGE))
        root_id = self._link().json()["id"]
        Integration.objects.filter(id=self.integration.id).update(kind="github")
        client.users_lookupByEmail.reset_mock()

        res = self.client.post(f"/api/projects/{self.team.id}/comments/{root_id}/unlink_slack_thread/")

        assert res.status_code == status.HTTP_204_NO_CONTENT
        client.users_lookupByEmail.assert_not_called()

    # Agents call these through the MCP server with OAuth tokens, and a custom action the scope check
    # doesn't know resolves to no scope, which refuses every scoped token.
    @patch("posthog.tasks.comment_slack_sync.import_linked_slack_thread.delay")
    @patch("posthog.api.comments.resolve_slack_user")
    @patch("posthog.api.comments.posthoganalytics.feature_enabled", return_value=True)
    @patch("posthog.api.comments.SlackIntegration")
    def test_a_token_with_comment_write_can_link_and_unlink(self, mock_slack, _flag, mock_profile, _import):
        from posthog.models.personal_api_key import PersonalAPIKey, hash_key_value
        from posthog.models.utils import generate_random_token_personal

        mock_profile.return_value = self.slack_profile
        self._mock_slack(mock_slack, _thread_page(ROOT_MESSAGE))
        value = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="agent", user=self.user, secure_value=hash_key_value(value), scopes=["comment:write"]
        )
        self.client.logout()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {value}")

        linked = self._link(scope="Insight", item_id="42")
        assert linked.status_code == status.HTTP_201_CREATED, linked.json()
        unlinked = self.client.post(f"/api/projects/{self.team.id}/comments/{linked.json()['id']}/unlink_slack_thread/")
        assert unlinked.status_code == status.HTTP_204_NO_CONTENT

    @patch("posthog.api.comments.is_scout_sandbox_request", return_value=True)
    @patch("posthog.api.comments.posthoganalytics.feature_enabled", return_value=True)
    @patch("posthog.api.comments.SlackIntegration")
    def test_a_scout_cannot_link_a_thread_to_a_ticket(self, mock_slack, _flag, _scout):
        # Scouts write to tickets through the reply endpoint only, which the serializer enforces.
        self._mock_slack(mock_slack, _thread_page(ROOT_MESSAGE))

        res = self._link()

        assert res.status_code == status.HTTP_403_FORBIDDEN
        mock_slack.return_value.client.conversations_replies.assert_not_called()

    @patch("posthog.api.comments.time.monotonic", side_effect=[0, 100])
    @patch("posthog.api.comments.posthoganalytics.feature_enabled", return_value=True)
    @patch("posthog.api.comments.SlackIntegration")
    def test_gives_up_on_a_slow_private_channel_member_list(self, mock_slack, _flag, _clock):
        # Each page has its own timeout, so without a limit on the scan a big channel holds the worker.
        Integration.objects.filter(id=self.integration.id).update(created_by=self.user)
        client = self._mock_slack(mock_slack, _thread_page(ROOT_MESSAGE))
        client.conversations_info.return_value["channel"].update({"is_private": True, "is_group": True})
        more = {"members": ["U1"], "response_metadata": {"next_cursor": "more"}}
        # Finite, so a scan with no limit ends (refused as "not in the channel") instead of hanging the test.
        client.conversations_members.side_effect = [more, more, {"members": ["U1"]}]

        res = self._link()

        assert res.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        assert client.conversations_members.call_count == 1

    @patch("posthog.api.comments.posthoganalytics.feature_enabled", return_value=True)
    def test_unlinking_refuses_a_discussion_that_was_sent_to_slack(self, _flag):
        # A sent discussion was written in PostHog, so it isn't a copy that's safe to remove.
        root = Comment.objects.create(
            team=self.team, scope="Ticket", item_id=str(self.ticket.id), content="opener", created_by=self.user
        )
        CommentSlackThread.objects.for_team(self.team.id).create(
            team=self.team,
            scope="Ticket",
            item_id=str(self.ticket.id),
            source_comment=root,
            integration=self.integration,
            slack_channel_id=CHANNEL,
            slack_thread_ts=ROOT_TS,
            slack_team_id="T123",
        )

        res = self.client.post(f"/api/projects/{self.team.id}/comments/{root.id}/unlink_slack_thread/")

        assert res.status_code == status.HTTP_400_BAD_REQUEST
        assert CommentSlackThread.objects.for_team(self.team.id).exists()
        root.refresh_from_db()
        assert not root.deleted

    @parameterized.expand(
        [
            ("email_thread", {"scope": "EmailThread"}, True, status.HTTP_403_FORBIDDEN),
            ("customer_thread", {"scope": "conversations_ticket"}, True, status.HTTP_400_BAD_REQUEST),
            # A task comment needs its task in item_context, which a Slack message can't supply.
            ("task_comment", {"scope": "task"}, True, status.HTTP_400_BAD_REQUEST),
            # Replay Vision notes have their own access check, which a Slack channel can't apply.
            ("observation_note", {"scope": next(iter(OBSERVATION_COMMENT_SCOPES))}, True, status.HTTP_400_BAD_REQUEST),
            ("unknown_ticket", {"item_id": "00000000-0000-0000-0000-000000000000"}, True, status.HTTP_400_BAD_REQUEST),
            ("feature_off", {}, False, status.HTTP_404_NOT_FOUND),
        ]
    )
    @patch("posthog.api.comments.SlackIntegration")
    def test_refuses_targets_the_caller_cannot_link_to(self, _name, overrides, flag_on, expected, mock_slack):
        self._mock_slack(mock_slack, _thread_page(ROOT_MESSAGE))

        with patch("posthog.api.comments.posthoganalytics.feature_enabled", return_value=flag_on):
            res = self._link(**overrides)

        assert res.status_code == expected, res.json()
        mock_slack.return_value.client.conversations_replies.assert_not_called()
        assert not CommentSlackThread.objects.for_team(self.team.id).exists()


class TestImportLinkedSlackThread(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.integration = Integration.objects.create(
            team=self.team, kind="slack", integration_id="T123", sensitive_config={"access_token": "t"}
        )
        self.root = Comment.objects.create(
            team=self.team,
            scope="Ticket",
            item_id="t-1",
            content="root",
            item_context={"from_slack": True, "slack_import_state": "pending"},
        )
        self.mirror = CommentSlackThread.objects.for_team(self.team.id).create(
            team=self.team,
            scope="Ticket",
            item_id="t-1",
            source_comment=self.root,
            integration=self.integration,
            slack_channel_id=CHANNEL,
            slack_thread_ts=ROOT_TS,
            slack_team_id="T123",
        )

    def _root_context(self) -> dict:
        self.root.refresh_from_db()
        return self.root.item_context or {}

    @patch("posthog.tasks.comment_slack_sync.mirror_comment_reply_to_slack.delay")
    @patch("posthog.tasks.comment_slack_sync.resolve_slack_user")
    @patch("posthog.tasks.comment_slack_sync.SlackIntegration")
    def test_imports_what_people_said_at_their_slack_times_once(self, mock_slack, mock_profile, mock_mirror_out):
        mock_profile.side_effect = lambda _client, user_id, workspace: {
            "name": {"U1": "Ada", "U2": "Grace"}[user_id],
            "email": None,
            "avatar": None,
            "team_id": "T999",
        }
        client = mock_slack.return_value.client
        client.chat_postMessage.return_value = {"ts": "1767225900.000001"}
        client.conversations_replies.return_value = _thread_page(
            ROOT_MESSAGE,
            {"ts": "1767225700.000001", "user": "U2", "text": "Thanks, taking a look"},
            {"ts": "1767225701.000001", "bot_id": "B1", "text": "PostHog bot echo"},
            {"ts": "1767225702.000001", "user": "U3", "subtype": "channel_join", "text": "joined"},
            {"ts": "1767225800.000001", "user": "U1", "text": "", "files": [{"name": "trace.png"}]},
        )

        import_linked_slack_thread(str(self.mirror.id))
        import_linked_slack_thread(str(self.mirror.id))

        replies = list(Comment.objects.filter(source_comment=self.root).order_by("created_at"))
        assert [(r.item_context["slack_author_name"], r.content) for r in replies] == [
            ("Grace", "Thanks, taking a look"),
            ("Ada", "📎 trace.png"),
        ]
        assert [r.created_at.isoformat() for r in replies] == [
            "2026-01-01T00:01:40.000001+00:00",
            "2026-01-01T00:03:20.000001+00:00",
        ]
        mock_mirror_out.assert_not_called()
        # The thread is told once that it's linked, however many times the import runs.
        client.chat_postMessage.assert_called_once()
        assert client.chat_postMessage.call_args.kwargs["thread_ts"] == ROOT_TS
        assert self._root_context()["slack_import_state"] == "done"

    @parameterized.expand(
        [
            # More history and room under the cap: the next page runs as its own task.
            ("more_pages", 0, "next-page", True, "pending"),
            # The cap is reached with history left: the root says the import was cut short.
            ("cap_reached", LINKED_THREAD_IMPORT_MESSAGE_LIMIT - 1, "next-page", False, "truncated"),
            ("last_page", 0, None, False, "done"),
        ]
    )
    @patch("posthog.tasks.comment_slack_sync.import_linked_slack_thread.apply_async")
    @patch("posthog.tasks.comment_slack_sync.resolve_slack_user")
    @patch("posthog.tasks.comment_slack_sync.SlackIntegration")
    def test_pages_through_the_history_up_to_the_cap(
        self, _name, seen, next_cursor, reschedules, state, mock_slack, mock_profile, mock_next_page
    ):
        mock_profile.return_value = {"name": "Grace", "email": None, "avatar": None, "team_id": "T999"}
        page = _thread_page({"ts": "1767225700.000001", "user": "U2", "text": "Yup"})
        if next_cursor:
            page = {**page, "has_more": True, "response_metadata": {"next_cursor": next_cursor}}
        mock_slack.return_value.client.conversations_replies.return_value = page

        import_linked_slack_thread(str(self.mirror.id), cursor="this-page", seen=seen)

        assert mock_next_page.called == reschedules
        if reschedules:
            assert mock_next_page.call_args.kwargs["kwargs"]["cursor"] == next_cursor
        assert self._root_context()["slack_import_state"] == state

    @patch("posthog.tasks.comment_slack_sync.resolve_slack_user")
    @patch("posthog.tasks.comment_slack_sync.SlackIntegration")
    def test_an_unresolved_author_retries_instead_of_saving_unknown(self, mock_slack, mock_profile):
        # The save is keyed on the Slack ts, so a reply saved as "Unknown" would never be corrected.
        mock_profile.return_value = {"name": "Unknown", "email": None, "avatar": None, "team_id": None}
        mock_slack.return_value.client.conversations_replies.return_value = _thread_page(
            ROOT_MESSAGE, {"ts": "1767225700.000001", "user": "U2", "text": "Yup"}
        )

        with self.assertRaises(Retry):
            import_linked_slack_thread.apply(args=(str(self.mirror.id),), kwargs={"cursor": "page"})
        assert not Comment.objects.filter(source_comment=self.root).exists()

        # On the last attempt the reply is kept, under "Unknown", rather than lost.
        import_linked_slack_thread.apply(
            args=(str(self.mirror.id),), kwargs={"cursor": "page"}, retries=import_linked_slack_thread.max_retries
        )
        saved = Comment.objects.get(source_comment=self.root)
        assert (saved.item_context or {})["slack_author_name"] == "Unknown"

    # resolve_slack_user hides users.info's Retry-After, so a fixed 30s retry would spend every attempt
    # inside one cooldown and save the authors as "Unknown".
    @parameterized.expand([("first_retry", 0, 60), ("second_retry", 1, 120)])
    @patch("posthog.tasks.comment_slack_sync.resolve_slack_user")
    @patch("posthog.tasks.comment_slack_sync.SlackIntegration")
    def test_an_unresolved_author_backs_off(self, _name, retries, wait, mock_slack, mock_profile):
        mock_profile.return_value = {"name": "Unknown", "email": None, "avatar": None, "team_id": None}
        mock_slack.return_value.client.conversations_replies.return_value = _thread_page(
            ROOT_MESSAGE, {"ts": "1767225700.000001", "user": "U2", "text": "Yup"}
        )

        with self.assertRaises(Retry) as raised:
            import_linked_slack_thread.apply(args=(str(self.mirror.id),), kwargs={"cursor": "page"}, retries=retries)

        assert raised.exception.when == wait

    def test_a_page_a_lost_worker_was_on_runs_again(self):
        # Acknowledged early, the page would be dropped with the worker and the root left at "pending".
        assert import_linked_slack_thread.acks_late is True
        assert import_linked_slack_thread.reject_on_worker_lost is True

    @patch("posthog.tasks.comment_slack_sync.SlackIntegration")
    def test_a_rate_limit_retries_after_slacks_retry_after(self, mock_slack):
        rate_limited = MagicMock()
        rate_limited.get.side_effect = lambda key, default=None: {"error": "ratelimited"}.get(key, default)
        # Longer than the 30 seconds the live sync waits at most: capped like that, five retries would
        # run out inside one cooldown and fail an import Slack would soon have allowed.
        rate_limited.headers = {"Retry-After": "300"}
        mock_slack.return_value.client.conversations_replies.side_effect = SlackApiError("ratelimited", rate_limited)

        with self.assertRaises(Retry) as raised:
            import_linked_slack_thread.apply(args=(str(self.mirror.id),), kwargs={"cursor": "page"})

        assert raised.exception.when == 300

    # A root left at "pending" would tell readers the history is still on its way.
    @parameterized.expand([("sync_switched_off",), ("integration_gone",)])
    @patch("posthog.tasks.comment_slack_sync.SlackIntegration")
    def test_an_import_that_cannot_start_says_so_on_the_root(self, case, mock_slack):
        if case == "integration_gone":
            Integration.objects.filter(id=self.integration.id).update(kind="github")
        with patch(
            "posthog.tasks.comment_slack_sync.posthoganalytics.feature_enabled",
            return_value=case != "sync_switched_off",
        ):
            import_linked_slack_thread(str(self.mirror.id))

        assert self._root_context()["slack_import_state"] == "failed"
        mock_slack.return_value.client.conversations_replies.assert_not_called()

    # The page is saved, but a next page that can't be queued would leave the root at "pending" for good.
    @patch("posthog.tasks.comment_slack_sync.import_linked_slack_thread.apply_async")
    @patch("posthog.tasks.comment_slack_sync.resolve_slack_user")
    @patch("posthog.tasks.comment_slack_sync.SlackIntegration")
    def test_a_next_page_that_cannot_be_queued_retries_then_says_failed(self, mock_slack, mock_profile, mock_next):
        mock_profile.return_value = {"name": "Grace", "email": None, "avatar": None, "team_id": "T999"}
        page = _thread_page({"ts": "1767225700.000001", "user": "U2", "text": "Yup"})
        mock_slack.return_value.client.conversations_replies.return_value = {
            **page,
            "has_more": True,
            "response_metadata": {"next_cursor": "next-page"},
        }
        mock_next.side_effect = ConnectionError("broker down")

        with self.assertRaises(Retry):
            import_linked_slack_thread.apply(args=(str(self.mirror.id),), kwargs={"cursor": "page"})
        assert self._root_context()["slack_import_state"] == "pending"

        import_linked_slack_thread.apply(
            args=(str(self.mirror.id),), kwargs={"cursor": "page"}, retries=import_linked_slack_thread.max_retries
        )
        assert self._root_context()["slack_import_state"] == "failed"

    @patch("posthog.tasks.comment_slack_sync.resolve_slack_user")
    @patch("posthog.tasks.comment_slack_sync.SlackIntegration")
    def test_a_reply_imported_after_the_thread_is_unlinked_is_not_saved(self, mock_slack, mock_profile):
        # Unlinking deletes the discussion, so a reply saved after it would hang off nothing anyone sees.
        def unlink_while_reading(*_args, **_kwargs):
            CommentSlackThread.objects.unscoped().filter(id=self.mirror.id).delete()
            return {"name": "Grace", "email": None, "avatar": None, "team_id": "T999"}

        mock_profile.side_effect = unlink_while_reading
        mock_slack.return_value.client.conversations_replies.return_value = _thread_page(
            ROOT_MESSAGE, {"ts": "1767225700.000001", "user": "U2", "text": "Yup"}
        )

        import_linked_slack_thread(str(self.mirror.id), cursor="page")

        assert not Comment.objects.filter(source_comment=self.root).exists()

    @patch("posthog.tasks.comment_slack_sync.SlackIntegration")
    def test_an_import_that_runs_out_of_retries_says_so_on_the_root(self, mock_slack):
        mock_slack.return_value.client.conversations_replies.side_effect = ConnectionError("Slack is down")

        import_linked_slack_thread.apply(
            args=(str(self.mirror.id),), kwargs={"cursor": "page"}, retries=import_linked_slack_thread.max_retries
        )

        assert self._root_context()["slack_import_state"] == "failed"


class TestLinkedThreadOutboundGuard(APIBaseTest):
    def setUp(self):
        super().setUp()
        cache.clear()
        self.integration = Integration.objects.create(
            team=self.team, kind="slack", integration_id="T123", sensitive_config={"access_token": "t"}
        )

    def _reply_on(self, *, linked: bool) -> Comment:
        root = Comment.objects.create(
            team=self.team,
            scope="Insight",
            item_id="42",
            content="root",
            item_context={"from_slack": True} if linked else None,
        )
        CommentSlackThread.objects.for_team(self.team.id).create(
            team=self.team,
            scope="Insight",
            item_id="42",
            source_comment=root,
            integration=self.integration,
            slack_channel_id=CHANNEL,
            slack_thread_ts=ROOT_TS,
            slack_team_id="T123",
        )
        with patch("posthog.tasks.comment_slack_sync.mirror_comment_reply_to_slack.delay"):
            return Comment.objects.create(
                team=self.team, scope="Insight", item_id="42", source_comment=root, content="internal note"
            )

    # Linking checks both rules once. A reply must not reach a thread that has since been shared with
    # another workspace, or that a customer has since turned into a support ticket.
    @parameterized.expand(
        [
            ("linked_internal_channel", True, {}, False, True),
            ("linked_channel_now_slack_connect", True, {"is_ext_shared": True, "is_shared": True}, False, False),
            ("linked_thread_now_a_ticket", True, {}, True, False),
            # A discussion sent to Slack chose its channel in PostHog, so the guard leaves it alone.
            ("sent_to_a_shared_channel", False, {"is_ext_shared": True, "is_shared": True}, False, True),
        ]
    )
    @patch("posthog.tasks.comment_slack_sync.posthoganalytics.feature_enabled", return_value=True)
    @patch("posthog.tasks.comment_slack_sync.SlackIntegration")
    def test_posts_into_a_linked_thread_only_while_it_stays_internal(
        self, _name, linked, channel_flags, now_a_ticket, posts, mock_slack, _flag
    ):
        client = mock_slack.return_value.client
        client.conversations_info.return_value = {"channel": {"id": CHANNEL, "is_channel": True, **channel_flags}}
        client.chat_postMessage.return_value = {"ts": "1791883000.000001"}
        reply = self._reply_on(linked=linked)
        if now_a_ticket:
            Ticket.objects.create_with_number(
                team=self.team,
                channel_source=Channel.SLACK,
                slack_channel_id=CHANNEL,
                slack_thread_ts=ROOT_TS,
                status=Status.OPEN,
            )

        mirror_comment_reply_to_slack(str(reply.id))

        assert client.chat_postMessage.called == posts


class TestIngestSlackDiscussionReply(APIBaseTest):
    @patch("posthog.tasks.comment_slack_sync.resolve_slack_user")
    @patch("posthog.tasks.comment_slack_sync.SlackIntegration")
    def test_saves_a_live_reply_once_per_slack_message(self, _mock_slack, mock_profile):
        mock_profile.return_value = {"name": "Grace", "email": self.user.email, "avatar": None, "team_id": "T123"}
        integration = Integration.objects.create(
            team=self.team, kind="slack", integration_id="T123", sensitive_config={"access_token": "t"}
        )
        root = Comment.objects.create(team=self.team, scope="Insight", item_id="42", content="root")
        mirror = CommentSlackThread.objects.for_team(self.team.id).create(
            team=self.team,
            scope="Insight",
            item_id="42",
            source_comment=root,
            integration=integration,
            slack_channel_id="C1",
            slack_thread_ts="100.1",
        )

        for _ in range(2):
            ingest_slack_discussion_reply(str(mirror.id), "U2", "on it", None, "100.2")

        reply = Comment.objects.get(source_comment=root)
        assert reply.content == "on it"
        assert reply.created_by == self.user
        assert reply.item_context == {
            "from_slack": True,
            "slack_message_ts": "100.2",
            "slack_author_name": "Grace",
            "slack_author_avatar": None,
        }
