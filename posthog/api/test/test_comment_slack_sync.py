from datetime import timedelta

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.utils import timezone

from celery.exceptions import Retry
from parameterized import parameterized
from rest_framework import status
from slack_sdk.errors import SlackApiError

from posthog.api.comments import _slack_thread_url
from posthog.helpers.slack_thread_mirror import escape_slack_mrkdwn
from posthog.models.comment import Comment, CommentSlackThread
from posthog.models.integration import Integration
from posthog.tasks.comment_slack_sync import (
    SLACK_SYNCED_TS_KEY,
    backfill_comment_slack_thread,
    mirror_comment_reply_to_slack,
)


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

    def _send(self, comment_id, channel_id: str = "C1", integration_id: int | None = None, channel_name: str = ""):
        return self.client.post(
            f"/api/projects/{self.team.id}/comments/{comment_id}/send_to_slack/",
            {
                "integration_id": integration_id or self.integration.id,
                "channel_id": channel_id,
                "channel_name": channel_name,
            },
        )

    @patch("posthog.api.comments.backfill_comment_slack_thread.delay")
    @patch("posthog.api.comments.posthoganalytics.feature_enabled", return_value=True)
    @patch("posthog.api.comments.SlackIntegration")
    def test_creates_mirror_posts_root_and_enqueues_backfill(self, mock_slack, _flag, mock_backfill):
        mock_slack.return_value.client.chat_postMessage.return_value = {"ts": "1700.1"}
        comment = self._comment()

        res = self._send(comment.id, channel_name="#team-support")

        assert res.status_code == status.HTTP_200_OK, res.json()
        mirror = CommentSlackThread.objects.for_team(self.team.id).get()
        assert mirror.source_comment_id == comment.id
        assert mirror.slack_thread_ts == "1700.1"
        assert (mirror.slack_channel_id, mirror.slack_team_id) == ("C1", "T123")
        # Channel name is stored for display with the leading # stripped.
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
