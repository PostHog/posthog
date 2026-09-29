from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.conversations.backend.facade.api import SupportMessageSendError, SupportSlackNotConfigured
from products.customer_analytics.backend.constants import DELIVERY_IN_FLIGHT_ERROR, DELIVERY_INTERRUPTED_ERROR
from products.customer_analytics.backend.logic.shoutouts import ShoutoutRateLimited
from products.customer_analytics.backend.models import Shoutout, ShoutoutDelivery
from products.customer_analytics.backend.tasks import send_announcement, send_shoutout

POST = "products.customer_analytics.backend.logic.shoutouts.post_support_message"

SEND_TASKS = [
    ("current_name", send_shoutout, "customer_analytics.send_shoutout"),
    ("pre_rename_name", send_announcement, "customer_analytics.send_announcement"),
]


class TestSendShoutout(BaseTest):
    def _make(self, channel_ids: list[str], message: str = "hi") -> Shoutout:
        shoutout = Shoutout.all_teams.create(
            team=self.team, message=message, total_channels=len(channel_ids), status=Shoutout.Status.PENDING
        )
        for channel_id in channel_ids:
            ShoutoutDelivery.all_teams.create(
                team=self.team, shoutout=shoutout, slack_channel_id=channel_id, slack_channel_name=channel_id
            )
        return shoutout

    def _delivery(self, shoutout: Shoutout, channel_id: str) -> ShoutoutDelivery:
        return ShoutoutDelivery.all_teams.get(shoutout=shoutout, slack_channel_id=channel_id)

    @parameterized.expand(SEND_TASKS)
    @patch(POST)
    def test_all_channels_succeed(self, _name: str, task, task_name: str, mock_post: MagicMock):
        mock_post.return_value = "111.222"

        shoutout = self._make(["C1", "C2"])
        task(str(shoutout.id), self.team.pk)

        shoutout.refresh_from_db()
        assert shoutout.status == Shoutout.Status.SENT
        assert (shoutout.sent_count, shoutout.failed_count) == (2, 0)
        assert shoutout.sent_at is not None
        assert mock_post.call_count == 2
        assert self._delivery(shoutout, "C1").slack_message_ts == "111.222"

    @patch(POST)
    def test_one_channel_failure_is_isolated(self, mock_post: MagicMock):
        def fake_post(team_id: int, channel_id: str, text: str) -> str:
            if channel_id == "Cfail":
                raise SupportMessageSendError("not_in_channel")
            return "1.0"

        mock_post.side_effect = fake_post

        shoutout = self._make(["Cok", "Cfail"])
        send_shoutout(str(shoutout.id), self.team.pk)

        shoutout.refresh_from_db()
        assert shoutout.status == Shoutout.Status.PARTIALLY_FAILED
        assert (shoutout.sent_count, shoutout.failed_count) == (1, 1)
        assert self._delivery(shoutout, "Cok").status == ShoutoutDelivery.Status.SENT
        failed = self._delivery(shoutout, "Cfail")
        assert failed.status == ShoutoutDelivery.Status.FAILED
        assert failed.error == "not_in_channel"

    @patch(POST)
    def test_no_slack_credentials_fails_all(self, mock_post: MagicMock):
        mock_post.side_effect = SupportSlackNotConfigured()

        shoutout = self._make(["C1", "C2"])
        send_shoutout(str(shoutout.id), self.team.pk)

        shoutout.refresh_from_db()
        assert shoutout.status == Shoutout.Status.FAILED
        assert shoutout.failed_count == 2
        assert "not connected" in self._delivery(shoutout, "C1").error
        assert mock_post.call_count == 1

    @patch(POST)
    def test_rerun_does_not_repost_to_already_sent_channels(self, mock_post: MagicMock):
        mock_post.return_value = "1"

        shoutout = self._make(["C1", "C2"])
        send_shoutout(str(shoutout.id), self.team.pk)
        assert mock_post.call_count == 2

        send_shoutout(str(shoutout.id), self.team.pk)
        assert mock_post.call_count == 2

    @patch(POST)
    def test_crashed_in_flight_row_is_never_reposted(self, mock_post: MagicMock):
        mock_post.return_value = "1"

        shoutout = self._make(["Ccrashed", "Cok"])
        ShoutoutDelivery.all_teams.filter(shoutout=shoutout, slack_channel_id="Ccrashed").update(
            error=DELIVERY_IN_FLIGHT_ERROR
        )

        send_shoutout(str(shoutout.id), self.team.pk)

        assert mock_post.call_count == 1
        assert mock_post.call_args.args[1] == "Cok"
        crashed = self._delivery(shoutout, "Ccrashed")
        assert crashed.status == ShoutoutDelivery.Status.FAILED
        assert crashed.error == DELIVERY_INTERRUPTED_ERROR

    @patch(POST)
    def test_rate_limited_channel_defers_once_then_fails(self, mock_post: MagicMock):
        mock_post.side_effect = SupportMessageSendError("ratelimited", retry_after=30.0)

        shoutout = self._make(["C1"])
        try:
            send_shoutout(str(shoutout.id), self.team.pk)
            raise AssertionError("expected ShoutoutRateLimited")
        except ShoutoutRateLimited:
            pass
        assert self._delivery(shoutout, "C1").status == ShoutoutDelivery.Status.PENDING

        send_shoutout(str(shoutout.id), self.team.pk)
        assert mock_post.call_count == 2
        assert self._delivery(shoutout, "C1").status == ShoutoutDelivery.Status.FAILED

    @patch(POST)
    def test_rate_limited_channel_sends_on_retry(self, mock_post: MagicMock):
        mock_post.side_effect = [SupportMessageSendError("ratelimited", retry_after=1.0), "9.9"]

        shoutout = self._make(["C1"])
        try:
            send_shoutout(str(shoutout.id), self.team.pk)
            raise AssertionError("expected ShoutoutRateLimited")
        except ShoutoutRateLimited:
            pass

        send_shoutout(str(shoutout.id), self.team.pk)
        shoutout.refresh_from_db()
        assert shoutout.status == Shoutout.Status.SENT
        assert self._delivery(shoutout, "C1").slack_message_ts == "9.9"

    @parameterized.expand(SEND_TASKS)
    def test_retry_config_is_not_inert(self, _name: str, task, task_name: str):
        # Bare max_retries without autoretry_for is silently inert; assert the wiring is real.
        assert task.name == task_name
        assert Exception in task.autoretry_for
        assert task.max_retries == 3
