from typing import Any, cast

import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import SimpleTestCase

from slack_sdk.errors import SlackApiError

from posthog.models.integration import Integration
from posthog.slack.channels import MAX_HEADER_CHARS, MAX_SECTION_CHARS

from products.alerts_platform.backend.delivery.message import MessageDetail
from products.alerts_platform.backend.delivery.slack import SlackTransport, blocks_for
from products.alerts_platform.backend.delivery.transport import DeliveryError, MessageHandle
from products.alerts_platform.backend.facade.contracts import AlertDestinationData
from products.alerts_platform.backend.tests.delivery_messages import alert_message

MESSAGE = alert_message(
    headline="API errors is firing",
    details=(MessageDetail(label="Value", value="300"), MessageDetail(label="Threshold", value="above 100")),
)


class TestSlackBlocks(SimpleTestCase):
    def test_the_headline_is_clipped_to_what_slack_accepts(self) -> None:
        message = alert_message(headline="x" * 400, details=())

        header = blocks_for(message)[0]
        assert len(header["text"]["text"]) <= MAX_HEADER_CHARS

    def test_every_detail_reaches_the_body(self) -> None:
        section = blocks_for(MESSAGE)[1]

        assert section["text"]["text"] == "*Value:* 300\n*Threshold:* above 100"

    def test_a_long_detail_keeps_the_body_inside_what_slack_accepts(self) -> None:
        message = alert_message(
            headline="API errors could not be checked",
            details=(
                MessageDetail(label="Error", value="x" * 5000),
                MessageDetail(label="Failed checks", value="3"),
            ),
        )

        section = blocks_for(message)[1]

        # Over the limit Slack rejects the send outright, so the alert reaches nobody. Clipping
        # the joined body instead would take the failure count out with the error.
        assert len(section["text"]["text"]) <= MAX_SECTION_CHARS
        assert "*Failed checks:* 3" in section["text"]["text"]

    def test_a_query_error_cannot_speak_as_slack_markup(self) -> None:
        message = alert_message(
            headline="API errors could not be checked",
            details=(MessageDetail(label="Error", value="no column <!channel> in <http://x|table>"),),
        )

        body = blocks_for(message)[1]["text"]["text"]

        assert "<!channel>" not in body
        assert "&lt;!channel&gt;" in body

    def test_a_message_without_details_carries_no_empty_section(self) -> None:
        blocks = blocks_for(alert_message(headline="API errors is resolved", details=()))

        assert [block["type"] for block in blocks] == ["header"]


class TestSlackTransport(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.integration = Integration.objects.create(team=self.team, kind="slack", integration_id="T-1", config={})
        self.target = cast(
            AlertDestinationData,
            {"type": "slack", "slack_workspace_id": self.integration.id, "slack_channel_id": "C-ENG"},
        )

    def _send(self, **overrides: Any) -> Any:
        with patch("products.alerts_platform.backend.delivery.slack.SlackIntegration") as slack_integration:
            slack_integration.return_value.client.chat_postMessage.return_value = {"ts": "1700000000.1"}
            handle = SlackTransport().deliver(
                team_id=overrides.pop("team_id", self.team.id),
                target=overrides.pop("target", self.target),
                message=MESSAGE,
                **overrides,
            )
        return handle, slack_integration.return_value.client.chat_postMessage

    def test_a_send_returns_the_handle_a_reply_needs(self) -> None:
        handle, post = self._send()

        assert handle == MessageHandle(external_ref={"channel": "C-ENG", "ts": "1700000000.1"})
        assert post.call_args.kwargs["thread_ts"] is None

    def test_a_reply_goes_into_the_thread_it_names(self) -> None:
        _, post = self._send(in_reply_to=MessageHandle(external_ref={"channel": "C-ENG", "ts": "1699999999.9"}))

        assert post.call_args.kwargs["thread_ts"] == "1699999999.9"

    def test_a_workspace_another_team_owns_is_refused(self) -> None:
        # An unscoped lookup finds the integration by id alone and sends into it.
        with pytest.raises(DeliveryError):
            self._send(team_id=self.team.id + 1)

    def test_a_refusal_from_slack_becomes_a_delivery_error(self) -> None:
        with patch("products.alerts_platform.backend.delivery.slack.SlackIntegration") as slack_integration:
            slack_integration.return_value.client.chat_postMessage.side_effect = SlackApiError(
                "channel_not_found", {"error": "channel_not_found"}
            )
            with pytest.raises(DeliveryError):
                SlackTransport().deliver(team_id=self.team.id, target=self.target, message=MESSAGE)

    def test_a_destination_missing_its_channel_is_refused(self) -> None:
        target = cast(AlertDestinationData, {"type": "slack", "slack_workspace_id": self.integration.id})

        with pytest.raises(DeliveryError):
            self._send(target=target)
