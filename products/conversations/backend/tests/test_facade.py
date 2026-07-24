from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized
from slack_sdk.errors import SlackApiError

from products.conversations.backend.facade.api import SupportMessageSendError, post_support_message

CLIENT = "products.conversations.backend.facade.api.get_slack_client"


class FakeSlackResponse(dict):
    # Mimics slack_sdk's SlackResponse: .get() reads the JSON body, HTTP headers are an attribute.
    def __init__(self, data: dict, headers: dict | None = None) -> None:
        super().__init__(data)
        self.headers = headers or {}


class TestPostSupportMessage(BaseTest):
    @patch(CLIENT)
    def test_applies_configured_bot_identity(self, mock_get_client: MagicMock):
        self.team.conversations_settings = {
            "slack_bot_display_name": "SupportBot",
            "slack_bot_icon_url": "https://example.com/icon.png",
        }
        self.team.save()
        client = MagicMock()
        client.chat_postMessage.return_value = {"ts": "111.222"}
        mock_get_client.return_value = client

        ts = post_support_message(self.team.pk, "C1", "hello team")

        assert ts == "111.222"
        kwargs = client.chat_postMessage.call_args.kwargs
        assert kwargs["channel"] == "C1"
        assert kwargs["text"] == "hello team"
        assert kwargs["username"] == "SupportBot"
        assert kwargs["icon_url"] == "https://example.com/icon.png"

    @parameterized.expand(
        [
            (
                "slack_rate_limited",
                SlackApiError(
                    message="x",
                    response=FakeSlackResponse({"error": "ratelimited"}, headers={"Retry-After": "7"}),
                ),
                None,
                "ratelimited",
                7.0,
            ),
            ("transport_error", ConnectionError("boom"), None, "transport_error", None),
            ("missing_ts", None, {"ok": True}, "missing_ts", None),
        ]
    )
    @patch(CLIENT)
    def test_translates_send_failures(
        self,
        _name: str,
        side_effect: Exception | None,
        return_value: dict | None,
        expected_code: str,
        expected_retry_after: float | None,
        mock_get_client: MagicMock,
    ):
        client = MagicMock()
        if side_effect is not None:
            client.chat_postMessage.side_effect = side_effect
        else:
            client.chat_postMessage.return_value = return_value
        mock_get_client.return_value = client

        with self.assertRaises(SupportMessageSendError) as ctx:
            post_support_message(self.team.pk, "C1", "hi")
        assert ctx.exception.code == expected_code
        assert ctx.exception.retry_after == expected_retry_after
