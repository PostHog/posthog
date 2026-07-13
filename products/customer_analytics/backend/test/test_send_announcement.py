from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from slack_sdk.errors import SlackApiError

from products.customer_analytics.backend.models import Announcement, AnnouncementDelivery
from products.customer_analytics.backend.tasks import send_announcement

CLIENT = "products.customer_analytics.backend.tasks.send_announcement.get_slack_client"


class TestSendAnnouncement(BaseTest):
    def _make(self, channel_ids: list[str], message: str = "hi") -> Announcement:
        announcement = Announcement.all_teams.create(
            team=self.team, message=message, total_channels=len(channel_ids), status=Announcement.Status.PENDING
        )
        for channel_id in channel_ids:
            AnnouncementDelivery.all_teams.create(
                team=self.team, announcement=announcement, slack_channel_id=channel_id, slack_channel_name=channel_id
            )
        return announcement

    def _delivery(self, announcement: Announcement, channel_id: str) -> AnnouncementDelivery:
        return AnnouncementDelivery.all_teams.get(announcement=announcement, slack_channel_id=channel_id)

    @patch(CLIENT)
    def test_all_channels_succeed(self, mock_get_client: MagicMock):
        client = MagicMock()
        client.chat_postMessage.return_value = {"ts": "111.222"}
        mock_get_client.return_value = client

        announcement = self._make(["C1", "C2"])
        send_announcement(str(announcement.id), self.team.pk)

        announcement.refresh_from_db()
        assert announcement.status == Announcement.Status.SENT
        assert (announcement.sent_count, announcement.failed_count) == (2, 0)
        assert announcement.sent_at is not None
        assert client.chat_postMessage.call_count == 2
        assert self._delivery(announcement, "C1").slack_message_ts == "111.222"

    @patch(CLIENT)
    def test_one_channel_failure_is_isolated(self, mock_get_client: MagicMock):
        def fake_post(channel: str, text: str, **kwargs):
            if channel == "Cfail":
                raise SlackApiError(message="x", response={"error": "not_in_channel"})
            return {"ts": "1.0"}

        client = MagicMock()
        client.chat_postMessage.side_effect = fake_post
        mock_get_client.return_value = client

        announcement = self._make(["Cok", "Cfail"])
        send_announcement(str(announcement.id), self.team.pk)

        announcement.refresh_from_db()
        assert announcement.status == Announcement.Status.PARTIALLY_FAILED
        assert (announcement.sent_count, announcement.failed_count) == (1, 1)
        assert self._delivery(announcement, "Cok").status == AnnouncementDelivery.Status.SENT
        failed = self._delivery(announcement, "Cfail")
        assert failed.status == AnnouncementDelivery.Status.FAILED
        assert failed.error == "not_in_channel"

    @patch(CLIENT)
    def test_no_slack_credentials_fails_all(self, mock_get_client: MagicMock):
        mock_get_client.side_effect = ValueError("Support Slack bot token is not configured")

        announcement = self._make(["C1"])
        send_announcement(str(announcement.id), self.team.pk)

        announcement.refresh_from_db()
        assert announcement.status == Announcement.Status.FAILED
        assert announcement.failed_count == 1
        assert "not connected" in self._delivery(announcement, "C1").error

    @patch(CLIENT)
    def test_rerun_does_not_repost_to_already_sent_channels(self, mock_get_client: MagicMock):
        client = MagicMock()
        client.chat_postMessage.return_value = {"ts": "1"}
        mock_get_client.return_value = client

        announcement = self._make(["C1", "C2"])
        send_announcement(str(announcement.id), self.team.pk)
        assert client.chat_postMessage.call_count == 2

        # Re-running must skip already-sent rows (idempotent on retry / duplicate dispatch).
        send_announcement(str(announcement.id), self.team.pk)
        assert client.chat_postMessage.call_count == 2

    @patch(CLIENT)
    def test_uses_configured_bot_identity(self, mock_get_client: MagicMock):
        self.team.conversations_settings = {
            "slack_bot_display_name": "SupportBot",
            "slack_bot_icon_url": "https://example.com/icon.png",
        }
        self.team.save()
        client = MagicMock()
        client.chat_postMessage.return_value = {"ts": "1"}
        mock_get_client.return_value = client

        announcement = self._make(["C1"], message="hello team")
        send_announcement(str(announcement.id), self.team.pk)

        kwargs = client.chat_postMessage.call_args.kwargs
        assert kwargs["channel"] == "C1"
        assert kwargs["text"] == "hello team"
        assert kwargs["username"] == "SupportBot"
        assert kwargs["icon_url"] == "https://example.com/icon.png"

    def test_retry_config_is_not_inert(self):
        # Guards the ported defect: bare max_retries/default_retry_delay without autoretry (or
        # bind + self.retry) silently never retries. Assert the autoretry wiring is real.
        assert Exception in send_announcement.autoretry_for
        assert send_announcement.max_retries == 3
