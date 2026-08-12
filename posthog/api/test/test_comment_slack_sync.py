from datetime import timedelta

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.db import IntegrityError
from django.utils import timezone

from celery.exceptions import Retry
from parameterized import parameterized
from rest_framework import status
from slack_sdk.errors import SlackApiError

from posthog.api.comments import _slack_thread_url
from posthog.helpers.slack_thread_mirror import _discussion_card_blocks, escape_slack_mrkdwn
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.comment import Comment, CommentSlackThread, SlackImportStatus
from posthog.models.integration import Integration
from posthog.models.team import Team
from posthog.tasks.comment_slack_sync import (
    BACKFILL_BATCH_SIZE,
    BACKFILL_RESCHEDULE_COUNTDOWN_SECONDS,
    SLACK_IMPORT_MAX_MESSAGES,
    SLACK_SYNCED_TS_KEY,
    backfill_comment_slack_thread,
    import_slack_thread_into_discussion,
    mirror_comment_reply_to_slack,
)


class TestDiscussionCardBlocks(APIBaseTest):
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
            # A mirror created by send_to_slack was never imported, so it reads as terminal and
            # the frontend never starts polling it.
            "import_status": "",
            "import_error": "",
            "imported_message_count": 0,
            "import_expected_count": 0,
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

    def test_slack_thread_lookup_skipped_when_flag_off(self):
        # Unflagged teams must not pay the mirror lookup on the hot comments endpoint.
        with patch("posthog.api.comments.posthoganalytics.feature_enabled", return_value=False):
            res = self.client.get(f"/api/projects/{self.team.id}/comments/{self.parent.id}/")
        assert res.status_code == status.HTTP_200_OK
        assert res.json()["slack_thread"] is None


class TestEscapeSlackMrkdwn(APIBaseTest):
    @parameterized.expand(
        [
            ("link_injection", "<https://evil|click>", "&lt;https://evil|click&gt;"),
            ("ampersand", "Tom & Jerry", "Tom &amp; Jerry"),
            ("plain", "Alice", "Alice"),
        ]
    )
    def test_escapes_slack_control_chars(self, _name, raw, expected):
        assert escape_slack_mrkdwn(raw) == expected


class TestImportSlackThread(APIBaseTest):
    """The import action: validate the thread is readable, then write the root and enqueue the rest."""

    URL = "https://acme.slack.com/archives/C1/p1700000000000100"

    def setUp(self):
        super().setUp()
        self.integration = Integration.objects.create(
            team=self.team,
            kind="slack",
            integration_id="T123",
            config={"authed_user": {"id": "u"}, "scope": "channels:history,groups:history,users:read,users:read.email"},
            sensitive_config={"access_token": "xoxb-test"},
            # The connector, so the private-channel guard doesn't mask what a test is asserting.
            created_by=self.user,
        )

    def _import(self, url: str | None = None, **overrides):
        body = {
            "integration_id": self.integration.id,
            "slack_url": url or self.URL,
            "scope": "Insight",
            "item_id": "42",
        }
        body.update(overrides)
        return self.client.post(f"/api/projects/{self.team.id}/comments/import_from_slack/", body)

    def _mock_slack(self, mock_slack, *, root: dict | None = None, is_private=False, missing_scopes=None, **flags):
        client = mock_slack.return_value.client
        mock_slack.return_value.missing_scopes.return_value = frozenset(missing_scopes or [])
        client.conversations_info.return_value = {
            "channel": {"id": "C1", "name": "team-support", "is_private": is_private, **flags}
        }
        client.conversations_replies.return_value = {
            "messages": [
                root
                if root is not None
                else {"ts": "1700000000.000100", "user": "U1", "text": "kickoff", "reply_count": 2}
            ]
        }
        return client


class TestImportSlackThreadValidation(TestImportSlackThread):
    @patch("posthog.api.comments.posthoganalytics.feature_enabled", return_value=False)
    def test_404_when_flag_off(self, _flag):
        # Fail-closed, same as send_to_slack: an unflagged team can't reach the importer at all.
        assert self._import().status_code == status.HTTP_404_NOT_FOUND
        assert not CommentSlackThread.objects.unscoped().exists()

    @parameterized.expand(
        [
            ("not_a_url", "nonsense"),
            ("wrong_host", "https://example.com/archives/C1/p1700000000000100"),
            ("http_not_https", "http://acme.slack.com/archives/C1/p1700000000000100"),
            ("no_message_in_path", "https://acme.slack.com/archives/C1"),
        ]
    )
    @patch("posthog.api.comments.posthoganalytics.feature_enabled", return_value=True)
    def test_rejects_a_link_that_isnt_a_slack_message(self, _name, url, _flag):
        res = self._import(url=url)

        assert res.status_code == status.HTTP_400_BAD_REQUEST, res.json()
        assert not CommentSlackThread.objects.unscoped().exists()
        assert not Comment.objects.filter(team=self.team).exists()

    @parameterized.expand([("ticket", "conversations_ticket"), ("task", "task"), ("canvas", "desktop_canvas")])
    @patch("posthog.api.comments.posthoganalytics.feature_enabled", return_value=True)
    def test_rejects_scopes_with_their_own_access_rules(self, _name, scope, _flag):
        res = self._import(scope=scope)

        assert res.status_code == status.HTTP_400_BAD_REQUEST, res.json()
        assert not CommentSlackThread.objects.unscoped().exists()

    @patch("posthog.api.comments.posthoganalytics.feature_enabled", return_value=True)
    def test_rejects_an_unknown_integration(self, _flag):
        res = self._import(integration_id=self.integration.id + 999)

        assert res.status_code == status.HTTP_400_BAD_REQUEST
        assert "integration not found" in str(res.json())

    @parameterized.expand(
        [
            ("not_in_channel", "not_in_channel", "/invite @PostHog"),
            ("channel_not_found", "channel_not_found", "can't see that Slack channel"),
            ("thread_not_found", "thread_not_found", "no longer exists"),
            ("missing_scope", "missing_scope", "Reconnect your Slack workspace"),
            ("ratelimited", "ratelimited", "rate limiting"),
        ]
    )
    @patch("posthog.api.comments.posthoganalytics.feature_enabled", return_value=True)
    @patch("posthog.api.comments.SlackIntegration")
    def test_unreadable_thread_explains_the_fix_and_writes_nothing(self, _name, code, expected, mock_slack, _flag):
        client = self._mock_slack(mock_slack)
        client.conversations_replies.side_effect = SlackApiError("boom", {"error": code})

        res = self._import()

        assert res.status_code == status.HTTP_400_BAD_REQUEST
        assert expected in res.json()["detail"], res.json()
        assert not CommentSlackThread.objects.unscoped().exists()
        assert not Comment.objects.filter(team=self.team).exists()

    @parameterized.expand([("public", False, "channels:history"), ("private", True, "groups:history")])
    @patch("posthog.api.comments.posthoganalytics.feature_enabled", return_value=True)
    @patch("posthog.api.comments.SlackIntegration")
    def test_requires_the_history_scope_for_the_channels_privacy(self, _name, is_private, scope, mock_slack, _flag):
        # A private channel needs groups:history; demanding both would reject a workspace that
        # can read the one we actually need.
        client = self._mock_slack(mock_slack, is_private=is_private, missing_scopes=[scope])

        res = self._import()

        assert res.status_code == status.HTTP_400_BAD_REQUEST
        assert "Reconnect your Slack workspace" in res.json()["detail"]
        assert scope in res.json()["detail"]
        client.conversations_replies.assert_not_called()

    @parameterized.expand([("dm", {"is_im": True}), ("group_dm", {"is_mpim": True})])
    @patch("posthog.api.comments.posthoganalytics.feature_enabled", return_value=True)
    @patch("posthog.api.comments.SlackIntegration")
    def test_cannot_import_a_direct_message(self, _name, flags, mock_slack, _flag):
        self._mock_slack(mock_slack, **flags)

        res = self._import()

        assert res.status_code == status.HTTP_400_BAD_REQUEST
        assert "direct message" in str(res.json())

    @patch("posthog.api.comments.posthoganalytics.feature_enabled", return_value=True)
    @patch("posthog.api.comments.SlackIntegration")
    def test_private_channel_is_limited_to_the_workspace_connector(self, mock_slack, _flag):
        self._mock_slack(mock_slack, is_private=True)
        self.integration.created_by = None
        self.integration.save()

        res = self._import()

        assert res.status_code == status.HTTP_403_FORBIDDEN
        assert not CommentSlackThread.objects.unscoped().exists()

    @patch("posthog.api.comments.posthoganalytics.feature_enabled", return_value=True)
    @patch("posthog.api.comments.SlackIntegration")
    def test_rejects_an_archived_channel(self, mock_slack, _flag):
        self._mock_slack(mock_slack, is_archived=True)

        res = self._import()

        assert res.status_code == status.HTTP_400_BAD_REQUEST
        assert "archived" in res.json()["detail"]

    @patch("posthog.api.comments.posthoganalytics.feature_enabled", return_value=True)
    @patch("posthog.api.comments.SlackIntegration")
    def test_rejects_a_thread_longer_than_the_cap(self, mock_slack, _flag):
        self._mock_slack(mock_slack, root={"ts": "1700000000.000100", "user": "U1", "text": "hi", "reply_count": 5000})

        res = self._import()

        assert res.status_code == status.HTTP_400_BAD_REQUEST
        assert str(SLACK_IMPORT_MAX_MESSAGES - 1) in res.json()["detail"]
        assert not CommentSlackThread.objects.unscoped().exists()

    @parameterized.expand(
        [
            ("bot", {"ts": "1700000000.000100", "bot_id": "B1", "text": "deploy finished"}),
            ("no_text", {"ts": "1700000000.000100", "user": "U1", "text": ""}),
        ]
    )
    @patch("posthog.tasks.comment_slack_sync.resolve_slack_user", return_value={"name": "Ann", "team_id": "T123"})
    @patch("posthog.api.comments.posthoganalytics.feature_enabled", return_value=True)
    @patch("posthog.api.comments.SlackIntegration")
    def test_rejects_a_root_it_cannot_represent(self, _name, root, mock_slack, _flag, _resolve):
        # Refusing up front is what stops a stub discussion being created for a thread whose
        # first message can't become a comment.
        self._mock_slack(mock_slack, root=root)

        res = self._import()

        assert res.status_code == status.HTTP_400_BAD_REQUEST, res.json()
        assert not CommentSlackThread.objects.unscoped().exists()
        assert not Comment.objects.filter(team=self.team).exists()


class TestImportSlackThreadCreation(TestImportSlackThread):
    @patch("posthog.api.comments.import_slack_thread_into_discussion.delay")
    @patch(
        "posthog.tasks.comment_slack_sync.resolve_slack_user",
        return_value={"name": "Ann", "team_id": "T123", "email": "ann@example.com", "avatar": "http://a/i.png"},
    )
    @patch("posthog.api.comments.posthoganalytics.feature_enabled", return_value=True)
    @patch("posthog.api.comments.SlackIntegration")
    def test_creates_the_root_and_enqueues_the_reply_backfill(self, mock_slack, _flag, _resolve, mock_import):
        self._mock_slack(mock_slack)

        with self.captureOnCommitCallbacks(execute=True):
            res = self._import()

        assert res.status_code == status.HTTP_201_CREATED, res.json()
        mirror = CommentSlackThread.objects.for_team(self.team.id).get()
        assert mirror.slack_thread_ts == "1700000000.000100"
        assert (mirror.slack_channel_id, mirror.slack_channel_name) == ("C1", "team-support")
        assert mirror.import_status == SlackImportStatus.PENDING
        # reply_count + the root, so the UI can show progress before the first reply lands.
        assert mirror.import_expected_count == 3
        assert mirror.imported_message_count == 1

        root = Comment.objects.get(team=self.team, id=mirror.source_comment_id)
        assert root.content == "kickoff"
        assert root.source_comment_id is None
        assert root.item_context["from_slack"] is True
        assert root.item_context["slack_message_ts"] == "1700000000.000100"
        # The Slack author's own time, not the import's — an old thread must not look brand new.
        assert root.created_at.timestamp() == 1700000000.0001
        mock_import.assert_called_once_with(comment_slack_thread_id=str(mirror.id))

    @patch("posthog.api.comments.import_slack_thread_into_discussion.delay")
    @patch("posthog.tasks.comment_slack_sync.resolve_slack_user", return_value={"name": "Ann", "team_id": "T123"})
    @patch("posthog.api.comments.posthoganalytics.feature_enabled", return_value=True)
    @patch("posthog.api.comments.SlackIntegration")
    def test_a_link_to_a_reply_anchors_on_the_thread_root(self, mock_slack, _flag, _resolve, _import):
        # "Copy link" on a reply yields the reply's ts in the path and the parent's in the query.
        # Anchoring on the reply would leave the mirror unreachable by the inbound webhook, which
        # only ever sees the parent's thread_ts.
        self._mock_slack(
            mock_slack,
            root={"ts": "1700000000.000100", "thread_ts": "1700000000.000100", "user": "U1", "text": "kickoff"},
        )

        res = self._import(
            url="https://acme.slack.com/archives/C1/p1700000999000999?thread_ts=1700000000.000100&cid=C1"
        )

        assert res.status_code == status.HTTP_201_CREATED, res.json()
        mirror = CommentSlackThread.objects.for_team(self.team.id).get()
        assert mirror.slack_thread_ts == "1700000000.000100"
        # The parent ts from the query string is what we asked Slack about.
        assert mock_slack.return_value.client.conversations_replies.call_args.kwargs["ts"] == "1700000000.000100"

    @patch("posthog.api.comments.import_slack_thread_into_discussion.delay")
    @patch("posthog.tasks.comment_slack_sync.resolve_slack_user", return_value={"name": "Ann", "team_id": "T123"})
    @patch("posthog.api.comments.posthoganalytics.feature_enabled", return_value=True)
    @patch("posthog.api.comments.SlackIntegration")
    def test_root_ts_comes_from_slack_not_the_link(self, mock_slack, _flag, _resolve, _import):
        # Slack stamps every threaded message with thread_ts = the true root, so a link that
        # resolves to a reply still anchors the mirror on the parent.
        self._mock_slack(
            mock_slack,
            root={"ts": "1700000999.000999", "thread_ts": "1700000000.000100", "user": "U1", "text": "kickoff"},
        )

        res = self._import()

        assert res.status_code == status.HTTP_201_CREATED, res.json()
        assert CommentSlackThread.objects.for_team(self.team.id).get().slack_thread_ts == "1700000000.000100"

    @patch("posthog.api.comments.import_slack_thread_into_discussion.delay")
    @patch("posthog.tasks.comment_slack_sync.resolve_slack_user", return_value={"name": "Ann", "team_id": "T123"})
    @patch("posthog.api.comments.posthoganalytics.feature_enabled", return_value=True)
    @patch("posthog.api.comments.SlackIntegration")
    def test_importing_the_same_thread_twice_is_a_conflict(self, mock_slack, _flag, _resolve, _import):
        self._mock_slack(mock_slack)
        assert self._import().status_code == status.HTTP_201_CREATED

        res = self._import(item_id="99")

        assert res.status_code == status.HTTP_409_CONFLICT, res.json()
        # Naming the existing discussion is what makes this actionable rather than a dead end.
        assert "/insights/42" in res.json()["detail"]
        assert CommentSlackThread.objects.unscoped().count() == 1

    @patch("posthog.api.comments.import_slack_thread_into_discussion.delay")
    @patch("posthog.tasks.comment_slack_sync.resolve_slack_user", return_value={"name": "Ann", "team_id": "T123"})
    @patch("posthog.api.comments.posthoganalytics.feature_enabled", return_value=True)
    @patch("posthog.api.comments.SlackIntegration")
    def test_one_activity_log_entry_for_the_import(self, mock_slack, _flag, _resolve, _import):
        # The reply backfill writes through bulk_create precisely so a 200-message import doesn't
        # land 200 rows in the activity log; the root still logs once, like any new comment.
        self._mock_slack(mock_slack)
        before = ActivityLog.objects.filter(team_id=self.team.id, scope="Insight").count()

        assert self._import().status_code == status.HTTP_201_CREATED

        assert ActivityLog.objects.filter(team_id=self.team.id, scope="Insight").count() == before + 1

    @patch("posthog.api.comments.import_slack_thread_into_discussion.delay")
    @patch("posthog.tasks.comment_slack_sync.resolve_slack_user", return_value={"name": "Ann", "team_id": "T123"})
    @patch("posthog.api.comments.posthoganalytics.feature_enabled", return_value=True)
    @patch("posthog.api.comments.SlackIntegration")
    def test_import_state_is_visible_on_the_comments_list(self, mock_slack, _flag, _resolve, _import):
        # The frontend polls the discussion list, so the import progress has to ride on the
        # comment's slack_thread rather than needing a second endpoint.
        self._mock_slack(mock_slack)
        assert self._import().status_code == status.HTTP_201_CREATED

        res = self.client.get(f"/api/projects/{self.team.id}/comments/?scope=Insight&item_id=42")

        assert res.status_code == status.HTTP_200_OK
        slack_thread = res.json()["results"][0]["slack_thread"]
        assert slack_thread["import_status"] == SlackImportStatus.PENDING
        assert slack_thread["import_expected_count"] == 3
        assert slack_thread["imported_message_count"] == 1

    def test_two_mirrors_on_one_slack_thread_are_rejected_by_the_database(self):
        # The inbound webhook resolves mirrors with .first(), so a duplicate would route replies
        # to an arbitrary discussion. The API checks first; this is the race backstop.
        root = Comment.objects.create(team=self.team, scope="Insight", item_id="42", content="a")
        other_root = Comment.objects.create(team=self.team, scope="Insight", item_id="43", content="b")
        shared = {
            "team": self.team,
            "scope": "Insight",
            "integration": self.integration,
            "slack_channel_id": "C1",
            "slack_thread_ts": "1700000000.000100",
        }
        CommentSlackThread.objects.for_team(self.team.id).create(source_comment=root, item_id="42", **shared)

        with self.assertRaises(IntegrityError):
            CommentSlackThread.objects.for_team(self.team.id).create(source_comment=other_root, item_id="43", **shared)

    def test_unposted_reservations_can_still_share_an_empty_ts(self):
        # send_to_slack reserves the row before it has a ts; the constraint must stay partial or
        # two concurrent sends in one channel would collide.
        root = Comment.objects.create(team=self.team, scope="Insight", item_id="42", content="a")
        other_root = Comment.objects.create(team=self.team, scope="Insight", item_id="43", content="b")
        shared = {
            "team": self.team,
            "scope": "Insight",
            "integration": self.integration,
            "slack_channel_id": "C1",
            "slack_thread_ts": "",
        }
        CommentSlackThread.objects.for_team(self.team.id).create(source_comment=root, item_id="42", **shared)
        CommentSlackThread.objects.for_team(self.team.id).create(source_comment=other_root, item_id="43", **shared)

        assert CommentSlackThread.objects.unscoped().filter(slack_thread_ts="").count() == 2


class TestImportSlackThreadTask(APIBaseTest):
    """The async half: walk conversations.replies and write the thread's history as comments."""

    ROOT_TS = "1700000000.000100"

    def setUp(self):
        super().setUp()
        self.integration = Integration.objects.create(
            team=self.team,
            kind="slack",
            integration_id="T123",
            config={"authed_user": {"id": "u"}},
            sensitive_config={"access_token": "xoxb-test"},
        )
        self.root = Comment.objects.create(
            team=self.team,
            scope="Insight",
            item_id="42",
            content="kickoff",
            item_context={"from_slack": True, "slack_message_ts": self.ROOT_TS},
        )
        self.mirror = CommentSlackThread.objects.for_team(self.team.id).create(
            team=self.team,
            scope="Insight",
            item_id="42",
            source_comment=self.root,
            integration=self.integration,
            slack_channel_id="C1",
            slack_thread_ts=self.ROOT_TS,
            slack_team_id="T123",
            import_status=SlackImportStatus.PENDING,
            import_expected_count=3,
            imported_message_count=1,
        )

    def _reply(self, ts: str, text: str = "a reply", **extra) -> dict:
        return {"ts": ts, "user": "U1", "text": text, **extra}

    def _run(self, mock_slack, pages: list[dict], **kwargs):
        mock_slack.return_value.client.conversations_replies.side_effect = pages
        import_slack_thread_into_discussion(comment_slack_thread_id=str(self.mirror.id), **kwargs)
        self.mirror.refresh_from_db()

    def _replies(self) -> list[Comment]:
        return list(Comment.objects.filter(team=self.team, source_comment_id=self.root.id).order_by("created_at"))

    @patch("posthog.tasks.comment_slack_sync.mirror_comment_reply_to_slack.delay")
    @patch("posthog.tasks.comment_slack_sync.resolve_slack_user", return_value={"name": "Ann", "team_id": "T123"})
    @patch("posthog.tasks.comment_slack_sync.SlackIntegration")
    def test_imports_replies_with_their_slack_timestamps_and_no_echo(self, mock_slack, _resolve, mock_mirror):
        self._run(
            mock_slack,
            [
                {
                    "messages": [
                        {"ts": self.ROOT_TS, "user": "U1", "text": "kickoff"},
                        self._reply("1700000100.000200", "first"),
                        self._reply("1700000200.000300", "second"),
                    ]
                }
            ],
        )

        replies = self._replies()
        assert [r.content for r in replies] == ["first", "second"]
        assert [r.created_at.timestamp() for r in replies] == [1700000100.0002, 1700000200.0003]
        assert all(r.item_context["from_slack"] is True for r in replies)
        # The root is already the discussion's thread root — importing it again would duplicate it.
        assert not any(r.content == "kickoff" for r in replies)
        # Every imported reply is Slack's own message; mirroring it back would loop.
        mock_mirror.assert_not_called()
        assert self.mirror.import_status == SlackImportStatus.COMPLETE
        assert self.mirror.imported_message_count == 3

    @patch("posthog.tasks.comment_slack_sync.resolve_slack_user", return_value={"name": "Ann", "team_id": "T123"})
    @patch("posthog.tasks.comment_slack_sync.SlackIntegration")
    def test_imported_replies_do_not_flood_the_activity_log(self, mock_slack, _resolve):
        before = ActivityLog.objects.filter(team_id=self.team.id).count()

        self._run(
            mock_slack,
            [{"messages": [self._reply(f"17000001{i:02d}.000200", f"reply {i}") for i in range(10)]}],
        )

        assert len(self._replies()) == 10
        assert ActivityLog.objects.filter(team_id=self.team.id).count() == before

    @parameterized.expand(
        [
            ("bot_id", {"ts": "1700000100.000200", "bot_id": "B1", "text": "deploy done"}),
            ("bot_message", {"ts": "1700000100.000200", "subtype": "bot_message", "text": "deploy done"}),
            ("app", {"ts": "1700000100.000200", "app_id": "A1", "user": "U2", "text": "from an app"}),
            ("slackbot", {"ts": "1700000100.000200", "user": "USLACKBOT", "text": "reminder"}),
            ("channel_join", {"ts": "1700000100.000200", "user": "U2", "subtype": "channel_join", "text": "joined"}),
            ("tombstone", {"ts": "1700000100.000200", "user": "U2", "subtype": "tombstone", "text": ""}),
        ]
    )
    @patch("posthog.tasks.comment_slack_sync.resolve_slack_user", return_value={"name": "Ann", "team_id": "T123"})
    @patch("posthog.tasks.comment_slack_sync.SlackIntegration")
    def test_skips_messages_a_discussion_cannot_represent(self, _name, message, mock_slack, _resolve):
        # Skipping bot_id is also what stops an import of a thread PostHog mirrors from
        # re-importing our own posts.
        self._run(mock_slack, [{"messages": [message]}])

        assert self._replies() == []
        assert self.mirror.import_status == SlackImportStatus.COMPLETE

    @patch("posthog.tasks.comment_slack_sync.resolve_slack_user", return_value={"name": "Ann", "team_id": "T123"})
    @patch("posthog.tasks.comment_slack_sync.SlackIntegration")
    def test_imports_a_file_share_caption(self, mock_slack, _resolve):
        self._run(
            mock_slack,
            [
                {
                    "messages": [
                        self._reply(
                            "1700000100.000200",
                            "here's the chart",
                            subtype="file_share",
                            files=[{"name": "chart.png", "permalink": "https://acme.slack.com/f/1"}],
                        )
                    ]
                }
            ],
        )

        assert "here's the chart" in self._replies()[0].content

    @patch("posthog.tasks.comment_slack_sync.import_slack_thread_into_discussion.apply_async")
    @patch("posthog.tasks.comment_slack_sync.resolve_slack_user", return_value={"name": "Ann", "team_id": "T123"})
    @patch("posthog.tasks.comment_slack_sync.SlackIntegration")
    def test_reschedules_itself_with_the_next_cursor(self, mock_slack, _resolve, mock_apply):
        self._run(
            mock_slack,
            [
                {
                    "messages": [self._reply("1700000100.000200", "page one")],
                    "response_metadata": {"next_cursor": "CURSOR2"},
                }
            ],
        )

        assert self.mirror.import_status == SlackImportStatus.IMPORTING
        mock_apply.assert_called_once()
        assert mock_apply.call_args.args[1] == {"cursor": "CURSOR2", "imported_replies": 1}

    @patch("posthog.tasks.comment_slack_sync.resolve_slack_user", return_value={"name": "Ann", "team_id": "T123"})
    @patch("posthog.tasks.comment_slack_sync.SlackIntegration")
    def test_a_rerun_creates_no_duplicates(self, mock_slack, _resolve):
        page = {"messages": [self._reply("1700000100.000200", "first")]}

        self._run(mock_slack, [page])
        CommentSlackThread.objects.unscoped().filter(id=self.mirror.id).update(import_status=SlackImportStatus.PENDING)
        self._run(mock_slack, [page])

        assert len(self._replies()) == 1

    @patch("posthog.tasks.comment_slack_sync.resolve_slack_user", return_value={"name": "Ann", "team_id": "T123"})
    @patch("posthog.tasks.comment_slack_sync.SlackIntegration")
    def test_stops_at_the_cap_and_says_so(self, mock_slack, _resolve):
        messages = [self._reply(f"17000001{i:04d}.000200", f"reply {i}") for i in range(SLACK_IMPORT_MAX_MESSAGES + 5)]

        self._run(mock_slack, [{"messages": messages, "response_metadata": {"next_cursor": "MORE"}}])

        assert self.mirror.import_status == SlackImportStatus.PARTIAL
        assert str(SLACK_IMPORT_MAX_MESSAGES) in self.mirror.import_error
        # The root already counted towards the cap.
        assert len(self._replies()) == SLACK_IMPORT_MAX_MESSAGES - 1

    @patch("posthog.tasks.comment_slack_sync._sync_killed", return_value=True)
    @patch("posthog.tasks.comment_slack_sync.SlackIntegration")
    def test_kill_switch_settles_the_row_instead_of_spinning(self, mock_slack, _killed):
        import_slack_thread_into_discussion(comment_slack_thread_id=str(self.mirror.id))
        self.mirror.refresh_from_db()

        assert self.mirror.import_status == SlackImportStatus.FAILED
        assert "turned off" in self.mirror.import_error
        assert self._replies() == []
        mock_slack.return_value.client.conversations_replies.assert_not_called()

    @patch("posthog.tasks.comment_slack_sync.SlackIntegration")
    def test_a_duplicate_delivery_on_a_settled_import_is_a_no_op(self, mock_slack):
        CommentSlackThread.objects.unscoped().filter(id=self.mirror.id).update(import_status=SlackImportStatus.COMPLETE)

        import_slack_thread_into_discussion(comment_slack_thread_id=str(self.mirror.id))

        mock_slack.return_value.client.conversations_replies.assert_not_called()

    @patch("posthog.tasks.comment_slack_sync.time.sleep")
    @patch("posthog.tasks.comment_slack_sync.resolve_slack_user", return_value={"name": "Ann", "team_id": "T123"})
    @patch("posthog.tasks.comment_slack_sync.SlackIntegration")
    def test_waits_out_a_rate_limit_once(self, mock_slack, _resolve, mock_sleep):
        response = MagicMock()
        response.get.side_effect = lambda key, default=None: {"error": "ratelimited"}.get(key, default)
        response.headers = {"Retry-After": "3"}

        self._run(
            mock_slack,
            [
                SlackApiError("ratelimited", response),
                {"messages": [self._reply("1700000100.000200", "after the wait")]},
            ],
        )

        mock_sleep.assert_called_once_with(3)
        assert [r.content for r in self._replies()] == ["after the wait"]
        assert self.mirror.import_status == SlackImportStatus.COMPLETE

    @patch("posthog.tasks.comment_slack_sync.resolve_slack_user", return_value={"name": "Ann", "team_id": "T123"})
    @patch("posthog.tasks.comment_slack_sync.SlackIntegration")
    def test_replies_land_on_the_project_team_not_the_environment(self, mock_slack, _resolve):
        # Comments are project-scoped: RootTeamMixin.save() resolves an environment team to its
        # parent, but the import writes through bulk_create, which skips save(). Without an explicit
        # resolve the replies would sit on a different team than their root and never render.
        child = Team.objects.create(organization=self.organization, name="child env", parent_team=self.team)
        self.integration.team = child
        self.integration.save()

        self._run(mock_slack, [{"messages": [self._reply("1700000100.000200", "in an environment")]}])

        reply = Comment.objects.get(source_comment_id=self.root.id)
        assert reply.team_id == self.team.id
        assert self._replies() == [reply]
