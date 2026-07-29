from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from posthog.api.comments import _slack_thread_url
from posthog.helpers.slack_thread_mirror import escape_slack_mrkdwn
from posthog.models.comment import Comment, CommentSlackThread
from posthog.models.integration import Integration
from posthog.tasks.comment_slack_sync import backfill_comment_slack_thread, mirror_comment_reply_to_slack


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

    def _send(self, comment_id, channel_id: str = "C1", integration_id: int | None = None):
        return self.client.post(
            f"/api/projects/{self.team.id}/comments/{comment_id}/send_to_slack/",
            {"integration_id": integration_id or self.integration.id, "channel_id": channel_id},
        )

    @patch("posthog.api.comments.backfill_comment_slack_thread.delay")
    @patch("posthog.api.comments.posthoganalytics.feature_enabled", return_value=True)
    @patch("posthog.api.comments.SlackIntegration")
    def test_creates_mirror_posts_root_and_enqueues_backfill(self, mock_slack, _flag, mock_backfill):
        mock_slack.return_value.client.chat_postMessage.return_value = {"ts": "1700.1"}
        comment = self._comment()

        res = self._send(comment.id)

        assert res.status_code == status.HTTP_200_OK, res.json()
        mirror = CommentSlackThread.objects.for_team(self.team.id).get()
        assert mirror.source_comment_id == comment.id
        assert mirror.slack_thread_ts == "1700.1"
        assert (mirror.slack_channel_id, mirror.slack_team_id) == ("C1", "T123")
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


class TestBackfill(APIBaseTest):
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
            slack_thread_ts="100.1",
        )

    @patch("posthog.tasks.comment_slack_sync.SlackIntegration")
    def test_backfills_replies_and_skips_from_slack(self, mock_slack):
        Comment.objects.create(team=self.team, scope="Insight", item_id="42", content="r1", source_comment=self.parent)
        Comment.objects.create(team=self.team, scope="Insight", item_id="42", content="r2", source_comment=self.parent)
        # A reply that came in from Slack must not be echoed back.
        Comment.objects.create(
            team=self.team,
            scope="Insight",
            item_id="42",
            content="from slack",
            source_comment=self.parent,
            item_context={"from_slack": True},
        )

        backfill_comment_slack_thread(str(self.mirror.id))

        # r1 + r2 only — the from_slack reply is skipped, and the root isn't a reply.
        assert mock_slack.return_value.client.chat_postMessage.call_count == 2


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
