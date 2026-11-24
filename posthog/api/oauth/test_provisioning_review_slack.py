import json
from typing import Any
from urllib.parse import urlencode

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import override_settings

from celery.exceptions import Retry
from parameterized import parameterized
from slack_sdk.errors import SlackApiError

from posthog.api.oauth.provisioning_review import decide_partner, settle_review
from posthog.api.oauth.provisioning_review_slack import (
    BLOCK_ACTION_ID,
    BLOCK_ID_PREFIX,
    BLOCK_MODAL_CALLBACK_ID,
    BLOCK_MODAL_REASON_BLOCK,
    BLOCK_MODAL_REASON_INPUT,
    THREAD_LOCK_PREFIX,
    THREAD_RETRY_SECONDS,
    _retry_countdown,
    _sync_review_slack_thread,
    block_partner_from_slack,
    interaction_ownership,
    sync_review_slack_thread,
)
from posthog.ingress.contracts import DeliveryOwnership
from posthog.ingress.dispatch.loading import reset_consumer_registry
from posthog.models.integration.slack import sign_slack_request
from posthog.models.oauth import OAuthApplication
from posthog.models.oauth_provisioning import ProvisioningConfig
from posthog.models.oauth_provisioning_review import (
    CIMDProvisioningReview,
    ProvisioningReviewStage,
    ProvisioningReviewStatus,
)
from posthog.models.user import User
from posthog.redis import get_client

POSTHOG_WORKSPACE = "T_POSTHOG"
REVIEW_CHANNEL = "C_REVIEWS"
SIGNING_SECRET = "review-bot-signing-secret"


def _slack_client(*, clicker_email: str = "", clicker_workspace: str = POSTHOG_WORKSPACE) -> MagicMock:
    client = MagicMock()
    client.chat_postMessage.return_value = {"channel": REVIEW_CHANNEL, "ts": "1700000000.000100"}
    client.auth_test.return_value = {"team_id": POSTHOG_WORKSPACE}
    client.users_info.return_value = MagicMock(
        data={"ok": True, "user": {"team_id": clicker_workspace, "profile": {"email": clicker_email}}}
    )
    return client


def _actions(blocks: list[dict[str, Any]]) -> list[str]:
    return [element["action_id"] for block in blocks if block["type"] == "actions" for element in block["elements"]]


@override_settings(PROVISIONING_REVIEW_SLACK_BOT_TOKEN="xoxb-posthog", PROVISIONING_REVIEW_SLACK_CHANNEL=REVIEW_CHANNEL)
@patch("posthog.api.oauth.provisioning_review.send_partner_review_email")
class TestProvisioningReviewSlack(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        cache.clear()
        self.app = OAuthApplication.objects.create(
            name="Example <!channel>",
            client_id="https://app.example.com/client.json",
            is_cimd_client=True,
            client_secret="",
            client_type=OAuthApplication.CLIENT_PUBLIC,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://app.example.com/callback",
            algorithm="RS256",
            is_provisioning_partner=True,
            _provisioning_config=ProvisioningConfig().model_dump(mode="json"),
        )
        self.review = CIMDProvisioningReview.objects.create(application=self.app, domain="example.com")

    def test_one_thread_follows_every_decision(self, _send_email) -> None:
        client = _slack_client()

        with (
            patch("posthog.api.oauth.provisioning_review_slack.SlackWebClient", return_value=client),
            self.captureOnCommitCallbacks(execute=True),
        ):
            settle_review(
                str(self.app.pk),
                status=ProvisioningReviewStatus.NEEDS_HUMAN,
                stage=ProvisioningReviewStage.RESEARCH,
                reason="Not sure",
            )

        posted = client.chat_postMessage.call_args.kwargs
        assert posted["channel"] == REVIEW_CHANNEL
        assert "&lt;!channel&gt;" in posted["text"]
        assert BLOCK_ACTION_ID in _actions(posted["blocks"])
        self.review.refresh_from_db()
        assert (self.review.slack_channel_id, self.review.slack_message_ts) == (REVIEW_CHANNEL, "1700000000.000100")

        client.reset_mock()
        with (
            patch("posthog.api.oauth.provisioning_review_slack.SlackWebClient", return_value=client),
            self.captureOnCommitCallbacks(execute=True),
        ):
            decide_partner(self.app, accept=False, reason="Staff: Malicious usage")

        updated = client.chat_update.call_args.kwargs
        assert updated["ts"] == "1700000000.000100"
        assert BLOCK_ACTION_ID not in _actions(updated["blocks"])
        reply = client.chat_postMessage.call_args.kwargs
        assert reply["thread_ts"] == "1700000000.000100"
        assert reply["text"] == "Needs staff review → Rejected: Staff: Malicious usage"

    def test_a_review_settled_where_the_bot_is_not_configured_still_queues_its_thread(self, _send_email) -> None:
        with (
            override_settings(PROVISIONING_REVIEW_SLACK_BOT_TOKEN="", PROVISIONING_REVIEW_SLACK_CHANNEL=""),
            patch("posthog.api.oauth.provisioning_review_slack.sync_review_slack_thread") as sync_task,
            self.captureOnCommitCallbacks(execute=True),
        ):
            settle_review(
                str(self.app.pk),
                status=ProvisioningReviewStatus.NEEDS_HUMAN,
                stage=ProvisioningReviewStage.RESEARCH,
                reason="Not sure",
            )

        sync_task.delay.assert_called_once_with(
            str(self.review.pk), ProvisioningReviewStatus.NEEDS_HUMAN, ProvisioningReviewStatus.PENDING, "Not sure"
        )

    @parameterized.expand(
        [
            ("same_decision_retried", ProvisioningReviewStatus.NEEDS_HUMAN, False),
            ("later_decision", ProvisioningReviewStatus.REJECTED, True),
        ]
    )
    def test_a_post_the_database_missed_is_reused(self, _send_email, _name, next_status, replies) -> None:
        client = _slack_client()

        with patch("posthog.api.oauth.provisioning_review_slack.SlackWebClient", return_value=client):
            with patch("django.db.models.query.QuerySet.update", side_effect=RuntimeError("database unavailable")):
                with self.assertRaises(RuntimeError):
                    _sync_review_slack_thread(
                        str(self.review.pk),
                        status=ProvisioningReviewStatus.NEEDS_HUMAN,
                        previous_status=None,
                        reason="",
                    )
            _sync_review_slack_thread(
                str(self.review.pk),
                status=next_status,
                previous_status=ProvisioningReviewStatus.NEEDS_HUMAN,
                reason="Staff: Malicious usage",
            )

        self.review.refresh_from_db()
        assert self.review.slack_message_ts == "1700000000.000100"
        assert client.chat_update.called is replies
        thread_replies = [c for c in client.chat_postMessage.call_args_list if "thread_ts" in c.kwargs]
        assert len(thread_replies) == (1 if replies else 0)
        assert client.chat_postMessage.call_count - len(thread_replies) == 1

    def test_a_held_thread_lock_defers_the_post(self, _send_email) -> None:
        client = _slack_client()
        get_client().lock(f"{THREAD_LOCK_PREFIX}:{self.review.pk}", timeout=60).acquire(blocking=False)

        with (
            patch("posthog.api.oauth.provisioning_review_slack.SlackWebClient", return_value=client),
            self.assertRaises(Retry),
        ):
            sync_review_slack_thread(str(self.review.pk), ProvisioningReviewStatus.NEEDS_HUMAN)

        client.chat_postMessage.assert_not_called()

    @parameterized.expand(
        [
            (
                "rate_limited",
                SlackApiError("ratelimited", MagicMock(status_code=429, headers={"Retry-After": "30"})),
                2,
                30,
            ),
            ("other_error", RuntimeError("boom"), 2, THREAD_RETRY_SECONDS * 4),
        ]
    )
    def test_retry_waits_as_long_as_slack_asks(self, _send_email, _name, error, retries, countdown) -> None:
        assert _retry_countdown(error, retries) == countdown

    @parameterized.expand(
        [
            ("staff_member", "staff@posthog.com", POSTHOG_WORKSPACE, True),
            ("member_who_isnt_staff", "member@posthog.com", POSTHOG_WORKSPACE, False),
            ("slack_connect_guest", "staff@posthog.com", "T_GUEST", False),
        ]
    )
    def test_only_staff_in_posthog_workspace_can_block(self, _send_email, _name, email, workspace, blocks) -> None:
        User.objects.create(email="staff@posthog.com", distinct_id="staff", is_staff=True)
        User.objects.create(email="member@posthog.com", distinct_id="member")

        with patch(
            "posthog.api.oauth.provisioning_review_slack.SlackWebClient",
            return_value=_slack_client(clicker_email=email, clicker_workspace=workspace),
        ):
            block_partner_from_slack(
                str(self.review.pk), slack_team_id=workspace, slack_user_id="U123", reason="Phishing"
            )

        self.app.refresh_from_db()
        assert self.app.provisioning.disabled is blocks
        if blocks:
            assert CIMDProvisioningReview.objects.get(pk=self.review.pk).reason == (
                "Staff (staff@posthog.com, from Slack): Phishing"
            )

    @override_settings(PROVISIONING_REVIEW_SLACK_SIGNING_SECRET=SIGNING_SECRET)
    def test_a_signed_block_form_reaches_the_block_task(self, _send_email) -> None:
        reset_consumer_registry()
        cache.clear()
        payload = {
            "type": "view_submission",
            "team": {"id": POSTHOG_WORKSPACE},
            "user": {"id": "U123"},
            "view": {
                "callback_id": BLOCK_MODAL_CALLBACK_ID,
                "private_metadata": json.dumps({"review_id": str(self.review.pk), "region": ""}),
                "state": {"values": {BLOCK_MODAL_REASON_BLOCK: {BLOCK_MODAL_REASON_INPUT: {"value": " Phishing "}}}},
            },
        }
        body = urlencode({"payload": json.dumps(payload)})
        signed = sign_slack_request(body.encode(), SIGNING_SECRET)

        with patch("posthog.api.oauth.provisioning_review_slack.block_partner_from_slack") as block_task:
            response = self.client.post(
                "/webhooks/provisioning-reviews/slack/interactivity",
                data=body,
                content_type="application/x-www-form-urlencoded",
                headers={"x-slack-signature": signed.signature, "x-slack-request-timestamp": signed.timestamp},
            )

        assert response.status_code == 202
        block_task.delay.assert_called_once_with(
            str(self.review.pk), slack_team_id=POSTHOG_WORKSPACE, slack_user_id="U123", reason="Phishing"
        )

    @parameterized.expand(
        [
            ("this_region", f"{BLOCK_ID_PREFIX}::review", DeliveryOwnership.LOCAL),
            ("other_region", f"{BLOCK_ID_PREFIX}:EU:review", DeliveryOwnership.ELSEWHERE),
            ("another_bot_button", "something_else", DeliveryOwnership.UNDECIDED),
        ]
    )
    def test_a_click_belongs_to_the_review_region(self, _send_email, _name, block_id, ownership) -> None:
        payload = {"type": "block_actions", "actions": [{"action_id": BLOCK_ACTION_ID, "block_id": block_id}]}

        assert interaction_ownership(payload) == ownership
