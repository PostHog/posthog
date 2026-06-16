from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from slack_sdk.errors import SlackApiError

from products.conversations.backend.models import Broadcast, BroadcastDelivery
from products.conversations.backend.tasks import send_broadcast


class TestSendBroadcast(APIBaseTest):
    def _make_broadcast(self, channel_ids: list[str], message: str = "hi") -> Broadcast:
        broadcast = Broadcast.all_teams.create(
            team=self.team,
            message=message,
            total_channels=len(channel_ids),
            status=Broadcast.Status.PENDING,
        )
        for channel_id in channel_ids:
            BroadcastDelivery.all_teams.create(
                team=self.team,
                broadcast=broadcast,
                slack_channel_id=channel_id,
                slack_channel_name=channel_id.lower(),
            )
        return broadcast

    def _delivery(self, broadcast: Broadcast, channel_id: str) -> BroadcastDelivery:
        return BroadcastDelivery.all_teams.get(broadcast=broadcast, slack_channel_id=channel_id)

    @patch("products.conversations.backend.tasks.get_slack_client")
    def test_all_channels_succeed(self, mock_get_client: MagicMock):
        client = MagicMock()
        client.chat_postMessage.return_value = {"ts": "111.222"}
        mock_get_client.return_value = client

        broadcast = self._make_broadcast(["C1", "C2"])
        send_broadcast(str(broadcast.id), self.team.pk)

        broadcast.refresh_from_db()
        assert broadcast.status == Broadcast.Status.SENT
        assert broadcast.sent_count == 2
        assert broadcast.failed_count == 0
        assert broadcast.sent_at is not None
        assert client.chat_postMessage.call_count == 2
        assert self._delivery(broadcast, "C1").slack_message_ts == "111.222"

    @patch("products.conversations.backend.tasks.get_slack_client")
    def test_one_channel_fails_does_not_abort_batch(self, mock_get_client: MagicMock):
        def fake_post(channel: str, text: str, **kwargs):
            if channel == "Cfail":
                raise SlackApiError(message="x", response={"error": "not_in_channel"})
            return {"ts": "1.0"}

        client = MagicMock()
        client.chat_postMessage.side_effect = fake_post
        mock_get_client.return_value = client

        broadcast = self._make_broadcast(["Cok", "Cfail"])
        send_broadcast(str(broadcast.id), self.team.pk)

        broadcast.refresh_from_db()
        assert broadcast.status == Broadcast.Status.PARTIALLY_FAILED
        assert broadcast.sent_count == 1
        assert broadcast.failed_count == 1
        assert self._delivery(broadcast, "Cok").status == BroadcastDelivery.Status.SENT
        failed = self._delivery(broadcast, "Cfail")
        assert failed.status == BroadcastDelivery.Status.FAILED
        assert failed.error == "not_in_channel"

    @patch("products.conversations.backend.tasks.get_slack_client")
    def test_no_slack_credentials_fails_all(self, mock_get_client: MagicMock):
        mock_get_client.side_effect = ValueError("Support Slack bot token is not configured")

        broadcast = self._make_broadcast(["C1"])
        send_broadcast(str(broadcast.id), self.team.pk)

        broadcast.refresh_from_db()
        assert broadcast.status == Broadcast.Status.FAILED
        assert broadcast.failed_count == 1
        assert "not connected" in self._delivery(broadcast, "C1").error

    @patch("products.conversations.backend.tasks.get_slack_client")
    def test_rerun_does_not_repost_to_already_sent_channels(self, mock_get_client: MagicMock):
        client = MagicMock()
        client.chat_postMessage.return_value = {"ts": "1"}
        mock_get_client.return_value = client

        broadcast = self._make_broadcast(["C1", "C2"])
        send_broadcast(str(broadcast.id), self.team.pk)
        assert client.chat_postMessage.call_count == 2

        # Re-running must skip already-sent rows (idempotent).
        send_broadcast(str(broadcast.id), self.team.pk)
        assert client.chat_postMessage.call_count == 2

    @patch("products.conversations.backend.tasks.get_slack_client")
    def test_uses_configured_bot_identity(self, mock_get_client: MagicMock):
        self.team.conversations_settings = {
            "slack_bot_display_name": "SupportBot",
            "slack_bot_icon_url": "https://example.com/icon.png",
        }
        self.team.save()
        client = MagicMock()
        client.chat_postMessage.return_value = {"ts": "1"}
        mock_get_client.return_value = client

        broadcast = self._make_broadcast(["C1"], message="hello team")
        send_broadcast(str(broadcast.id), self.team.pk)

        kwargs = client.chat_postMessage.call_args.kwargs
        assert kwargs["channel"] == "C1"
        assert kwargs["text"] == "hello team"
        assert kwargs["username"] == "SupportBot"
        assert kwargs["icon_url"] == "https://example.com/icon.png"
