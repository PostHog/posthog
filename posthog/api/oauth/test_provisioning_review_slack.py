import json
from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import override_settings

from parameterized import parameterized

from posthog.api.oauth.provisioning_review import decide_partner, settle_review
from posthog.api.oauth.provisioning_review_slack import (
    BLOCK_ACTION_ID,
    BLOCK_MODAL_CALLBACK_ID,
    BLOCK_MODAL_REASON_BLOCK,
    BLOCK_MODAL_REASON_INPUT,
    handle_block_modal_submit,
)
from posthog.models.oauth import OAuthApplication
from posthog.models.oauth_provisioning import ProvisioningConfig
from posthog.models.oauth_provisioning_review import (
    CIMDProvisioningReview,
    ProvisioningReviewStage,
    ProvisioningReviewStatus,
)
from posthog.models.user import User

POSTHOG_WORKSPACE = "T_POSTHOG"
REVIEW_CHANNEL = "C_REVIEWS"


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

    @parameterized.expand(
        [
            ("staff_member", "staff@posthog.com", POSTHOG_WORKSPACE, "Phishing", True, None),
            ("member_who_isnt_staff", "member@posthog.com", POSTHOG_WORKSPACE, "Phishing", False, "Only PostHog"),
            ("slack_connect_guest", "staff@posthog.com", "T_GUEST", "Phishing", False, "Only PostHog"),
            ("no_reason", "staff@posthog.com", POSTHOG_WORKSPACE, "  ", False, "Enter a reason"),
        ]
    )
    def test_block_from_slack(self, _send_email, _name, email, workspace, reason, blocks, error) -> None:
        User.objects.create(email="staff@posthog.com", distinct_id="staff", is_staff=True)
        User.objects.create(email="member@posthog.com", distinct_id="member")
        payload = {
            "type": "view_submission",
            "team": {"id": workspace},
            "user": {"id": "U123"},
            "view": {
                "callback_id": BLOCK_MODAL_CALLBACK_ID,
                "private_metadata": json.dumps({"review_id": str(self.review.pk), "region": ""}),
                "state": {"values": {BLOCK_MODAL_REASON_BLOCK: {BLOCK_MODAL_REASON_INPUT: {"value": reason}}}},
            },
        }

        with patch(
            "posthog.api.oauth.provisioning_review_slack.SlackWebClient",
            return_value=_slack_client(clicker_email=email, clicker_workspace=workspace),
        ):
            response = handle_block_modal_submit(payload)

        self.app.refresh_from_db()
        assert self.app.provisioning.disabled is blocks
        if error is None:
            assert response is None
            assert CIMDProvisioningReview.objects.get(pk=self.review.pk).reason.startswith(
                "Staff (staff@posthog.com, from Slack)"
            )
        else:
            assert response is not None
            assert error in response["errors"][BLOCK_MODAL_REASON_BLOCK]
