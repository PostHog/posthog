from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from products.conversations.backend.facade.api import SupportMessageSendError, SupportSlackNotConfigured
from products.customer_analytics.backend.constants import DELIVERY_IN_FLIGHT_ERROR, DELIVERY_INTERRUPTED_ERROR
from products.customer_analytics.backend.logic.announcements import AnnouncementRateLimited
from products.customer_analytics.backend.models import Announcement, AnnouncementDelivery
from products.customer_analytics.backend.tasks import send_announcement

POST = "products.customer_analytics.backend.logic.announcements.post_support_message"


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

    @patch(POST)
    def test_all_channels_succeed(self, mock_post: MagicMock):
        mock_post.return_value = "111.222"

        announcement = self._make(["C1", "C2"])
        send_announcement(str(announcement.id), self.team.pk)

        announcement.refresh_from_db()
        assert announcement.status == Announcement.Status.SENT
        assert (announcement.sent_count, announcement.failed_count) == (2, 0)
        assert announcement.sent_at is not None
        assert mock_post.call_count == 2
        assert self._delivery(announcement, "C1").slack_message_ts == "111.222"

    @patch(POST)
    def test_one_channel_failure_is_isolated(self, mock_post: MagicMock):
        def fake_post(team_id: int, channel_id: str, text: str) -> str:
            if channel_id == "Cfail":
                raise SupportMessageSendError("not_in_channel")
            return "1.0"

        mock_post.side_effect = fake_post

        announcement = self._make(["Cok", "Cfail"])
        send_announcement(str(announcement.id), self.team.pk)

        announcement.refresh_from_db()
        assert announcement.status == Announcement.Status.PARTIALLY_FAILED
        assert (announcement.sent_count, announcement.failed_count) == (1, 1)
        assert self._delivery(announcement, "Cok").status == AnnouncementDelivery.Status.SENT
        failed = self._delivery(announcement, "Cfail")
        assert failed.status == AnnouncementDelivery.Status.FAILED
        assert failed.error == "not_in_channel"

    @patch(POST)
    def test_no_slack_credentials_fails_all(self, mock_post: MagicMock):
        mock_post.side_effect = SupportSlackNotConfigured()

        announcement = self._make(["C1", "C2"])
        send_announcement(str(announcement.id), self.team.pk)

        announcement.refresh_from_db()
        assert announcement.status == Announcement.Status.FAILED
        assert announcement.failed_count == 2
        assert "not connected" in self._delivery(announcement, "C1").error
        assert mock_post.call_count == 1

    @patch(POST)
    def test_rerun_does_not_repost_to_already_sent_channels(self, mock_post: MagicMock):
        mock_post.return_value = "1"

        announcement = self._make(["C1", "C2"])
        send_announcement(str(announcement.id), self.team.pk)
        assert mock_post.call_count == 2

        send_announcement(str(announcement.id), self.team.pk)
        assert mock_post.call_count == 2

    @patch(POST)
    def test_crashed_in_flight_row_is_never_reposted(self, mock_post: MagicMock):
        mock_post.return_value = "1"

        announcement = self._make(["Ccrashed", "Cok"])
        AnnouncementDelivery.all_teams.filter(announcement=announcement, slack_channel_id="Ccrashed").update(
            error=DELIVERY_IN_FLIGHT_ERROR
        )

        send_announcement(str(announcement.id), self.team.pk)

        assert mock_post.call_count == 1
        assert mock_post.call_args.args[1] == "Cok"
        crashed = self._delivery(announcement, "Ccrashed")
        assert crashed.status == AnnouncementDelivery.Status.FAILED
        assert crashed.error == DELIVERY_INTERRUPTED_ERROR

    @patch(POST)
    def test_rate_limited_channel_defers_once_then_fails(self, mock_post: MagicMock):
        mock_post.side_effect = SupportMessageSendError("ratelimited", retry_after=30.0)

        announcement = self._make(["C1"])
        try:
            send_announcement(str(announcement.id), self.team.pk)
            raise AssertionError("expected AnnouncementRateLimited")
        except AnnouncementRateLimited:
            pass
        assert self._delivery(announcement, "C1").status == AnnouncementDelivery.Status.PENDING

        send_announcement(str(announcement.id), self.team.pk)
        assert mock_post.call_count == 2
        assert self._delivery(announcement, "C1").status == AnnouncementDelivery.Status.FAILED

    @patch(POST)
    def test_rate_limited_channel_sends_on_retry(self, mock_post: MagicMock):
        mock_post.side_effect = [SupportMessageSendError("ratelimited", retry_after=1.0), "9.9"]

        announcement = self._make(["C1"])
        try:
            send_announcement(str(announcement.id), self.team.pk)
            raise AssertionError("expected AnnouncementRateLimited")
        except AnnouncementRateLimited:
            pass

        send_announcement(str(announcement.id), self.team.pk)
        announcement.refresh_from_db()
        assert announcement.status == Announcement.Status.SENT
        assert self._delivery(announcement, "C1").slack_message_ts == "9.9"

    def test_retry_config_is_not_inert(self):
        # Bare max_retries without autoretry_for is silently inert; assert the wiring is real.
        assert Exception in send_announcement.autoretry_for
        assert send_announcement.max_retries == 3
