from datetime import datetime
from typing import Any, List
from unittest.mock import MagicMock, call, patch

import pytz
from freezegun import freeze_time

from posthog.models.dashboard import Dashboard
from posthog.models.dashboard_tile import DashboardTile
from posthog.models.insight import Insight
from posthog.models.instance_setting import set_instance_setting
from posthog.models.subscription import Subscription
from posthog.tasks.subscriptions import (
    _get_tiles_ordered_by_position,
    deliver_new_subscription,
    deliver_subscription_report,
    schedule_all_subscriptions,
)
from posthog.tasks.test.utils_email_tests import mock_email_messages
from posthog.test.base import APIBaseTest
from posthog.test.db_context_capturing import capture_db_queries


def _create_subscription(**kwargs: Any) -> Subscription:
    return Subscription.objects.create(
        target_type="email",
        target_value="test1@posthog.com,test2@posthog.com",
        frequency="daily",
        interval=1,
        start_date=datetime(2022, 1, 1, 9, 0).replace(tzinfo=pytz.UTC),
        **kwargs,
    )


@patch("posthog.tasks.subscriptions.group")
@patch("posthog.tasks.subscriptions.export_task")
@patch("posthog.tasks.subscriptions.EmailMessage")
@freeze_time("2022-02-02T08:55:00.000Z")
class TestSubscriptionsTasks(APIBaseTest):
    subscriptions: List[Subscription] = None  # type: ignore
    dashboard: Dashboard
    insight: Insight
    tiles: List[DashboardTile] = None  # type: ignore

    def setUp(self) -> None:
        self.dashboard = Dashboard.objects.create(team=self.team, name="private dashboard", created_by=self.user)
        self.insight = Insight.objects.create(team=self.team, short_id="123456", name="My Test subscription")
        self.tiles = []
        for _ in range(10):
            self.tiles.append(DashboardTile.objects.create(dashboard=self.dashboard, insight=self.insight))

        set_instance_setting("EMAIL_HOST", "fake_host")
        set_instance_setting("EMAIL_ENABLED", True)

        self.subscriptions = [
            _create_subscription(team=self.team, insight=self.insight, created_by=self.user),
            _create_subscription(team=self.team, insight=self.insight, created_by=self.user),
            _create_subscription(team=self.team, dashboard=self.dashboard, created_by=self.user),
            _create_subscription(team=self.team, dashboard=self.dashboard, created_by=self.user, deleted=True),
        ]

    @patch("posthog.tasks.subscriptions.deliver_subscription_report")
    def test_subscription_delivery_scheduling(
        self,
        mock_deliver_task: MagicMock,
        MockEmailMessage: MagicMock,
        mock_export_task: MagicMock,
        mock_group: MagicMock,
    ) -> None:
        # Modify a subscription to have its target time at least an hour ahead
        self.subscriptions[2].start_date = datetime(2022, 1, 1, 10, 0).replace(tzinfo=pytz.UTC)
        self.subscriptions[2].save()
        assert self.subscriptions[2].next_delivery_date == datetime(2022, 2, 2, 10, 0).replace(tzinfo=pytz.UTC)

        schedule_all_subscriptions()

        assert mock_deliver_task.delay.mock_calls == [call(self.subscriptions[0].id), call(self.subscriptions[1].id)]

    def test_subscription_delivery(
        self, MockEmailMessage: MagicMock, mock_export_task: MagicMock, mock_group: MagicMock
    ) -> None:
        mocked_email_messages = mock_email_messages(MockEmailMessage)

        deliver_subscription_report(self.subscriptions[0].id)

        assert len(mocked_email_messages) == 2
        assert mocked_email_messages[0].send.call_count == 1
        assert "is ready!" in mocked_email_messages[0].html_body
        assert f"/exporter/export-my-test-subscription.png?token=ey" in mocked_email_messages[0].html_body

        assert mock_export_task.s.call_count == 1

    def test_new_subscription_delivery(
        self, MockEmailMessage: MagicMock, mock_export_task: MagicMock, mock_group: MagicMock
    ) -> None:
        mocked_email_messages = mock_email_messages(MockEmailMessage)

        deliver_new_subscription(
            self.subscriptions[0].id, new_emails=["test@posthog.com"], invite_message="My invite message"
        )

        assert len(mocked_email_messages) == 1
        assert mocked_email_messages[0].send.call_count == 1

        assert f"({self.user.email}) has subscribed you" in mocked_email_messages[0].html_body
        assert "Someone subscribed you to a PostHog Insight" == mocked_email_messages[0].subject
        assert "My invite message" in mocked_email_messages[0].html_body
        assert mock_export_task.s.call_count == 1

    def test_should_have_different_text_for_self(
        self, MockEmailMessage: MagicMock, mock_export_task: MagicMock, mock_group: MagicMock
    ) -> None:
        mocked_email_messages = mock_email_messages(MockEmailMessage)

        deliver_new_subscription(
            self.subscriptions[0].id, new_emails=[self.user.email], invite_message="My invite message"
        )

        assert len(mocked_email_messages) == 1
        assert mocked_email_messages[0].send.call_count == 1
        assert "You have been subscribed" in mocked_email_messages[0].html_body
        assert "You have been subscribed to a PostHog Insight" == mocked_email_messages[0].subject

    def test_sends_dashboard_subscription(
        self, MockEmailMessage: MagicMock, mock_export_task: MagicMock, mock_group: MagicMock
    ) -> None:
        mocked_email_messages = mock_email_messages(MockEmailMessage)

        subscription = _create_subscription(team=self.team, dashboard=self.dashboard, created_by=self.user)

        deliver_new_subscription(
            subscription.id, new_emails=[self.user.email], invite_message="My invite message",
        )

        assert len(mocked_email_messages) == 1
        assert mocked_email_messages[0].send.call_count == 1
        assert "You have been subscribed" in mocked_email_messages[0].html_body
        assert "You have been subscribed to a PostHog Dashboard" == mocked_email_messages[0].subject
        assert f"SHOWING 6 OF {len(self.tiles)} DASHBOARD INSIGHTS" in mocked_email_messages[0].html_body
        assert mock_export_task.s.call_count == 6

    def test_loads_dashboard_tiles_efficiently(
        self, MockEmailMessage: MagicMock, mock_export_task: MagicMock, mock_group: MagicMock
    ) -> None:
        with capture_db_queries() as capture_query_context:
            tiles = _get_tiles_ordered_by_position(dashboard=self.dashboard)

            for tile in tiles:
                assert tile.insight.id

            assert len(tiles) == 10

        assert len(capture_query_context.captured_queries) == 1
