from typing import Any, cast

import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import SimpleTestCase

from posthog.models.integration import Integration

from products.alerts.backend.delivery.message import AlertMessage
from products.alerts.backend.delivery.slack import SlackTransport, blocks_for
from products.alerts.backend.delivery.transport import DeliveryError, MessageHandle
from products.alerts.backend.facade.contracts import AlertDestinationData, AlertEventKind

MESSAGE = AlertMessage(
    headline="API errors is firing",
    details=(("Value", "300"), ("Threshold", "above 100")),
    kind=AlertEventKind.FIRING,
)


class TestSlackBlocks(SimpleTestCase):
    def test_the_headline_is_clipped_to_what_slack_accepts(self) -> None:
        message = AlertMessage(headline="x" * 400, details=(), kind=AlertEventKind.FIRING)

        header = blocks_for(message)[0]
        assert len(header["text"]["text"]) <= 150

    def test_every_detail_reaches_the_body(self) -> None:
        section = blocks_for(MESSAGE)[1]

        assert section["text"]["text"] == "*Value:* 300\n*Threshold:* above 100"

    def test_a_message_without_details_carries_no_empty_section(self) -> None:
        blocks = blocks_for(AlertMessage(headline="API errors is resolved", details=(), kind=AlertEventKind.RESOLVED))

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
        with patch("products.alerts.backend.delivery.slack.SlackIntegration") as slack_integration:
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

    def test_a_destination_missing_its_channel_is_refused(self) -> None:
        target = cast(AlertDestinationData, {"type": "slack", "slack_workspace_id": self.integration.id})

        with pytest.raises(DeliveryError):
            self._send(target=target)
