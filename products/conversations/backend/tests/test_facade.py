from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from slack_sdk.errors import SlackApiError

from products.conversations.backend.facade.api import post_support_message
from products.conversations.backend.facade.contracts import SupportMessageSendError

CLIENT = "products.conversations.backend.facade.api.get_slack_client"


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

    @patch(CLIENT)
    def test_translates_slack_errors_with_rate_limit_wait(self, mock_get_client: MagicMock):
        client = MagicMock()
        client.chat_postMessage.side_effect = SlackApiError(
            message="x", response={"error": "rate_limited", "headers": {"Retry-After": "7"}}
        )
        mock_get_client.return_value = client

        try:
            post_support_message(self.team.pk, "C1", "hi")
            raise AssertionError("expected SupportMessageSendError")
        except SupportMessageSendError as e:
            assert e.code == "rate_limited"
            assert e.retry_after == 7.0
