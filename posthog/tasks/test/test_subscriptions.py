from datetime import datetime
from typing import Any, List
from unittest.mock import MagicMock, call, patch

import pytz
from freezegun import freeze_time

from posthog.models.insight import Insight
from posthog.models.instance_setting import set_instance_setting
from posthog.models.subscription import Subscription
from posthog.tasks.subscriptions import (
    deliver_new_subscription,
    deliver_subscription_report,
    schedule_all_subscriptions,
)
from posthog.tasks.test.utils_email_tests import mock_email_messages
from posthog.test.base import APIBaseTest


def _create_insight_subscription(**kwargs: Any) -> Subscription:
    return Subscription.objects.create(
        target_type="email",
        target_value="test1@posthog.com,test2@posthog.com",
        frequency="daily",
        interval=1,
        start_date=datetime(2022, 1, 1, 9, 0).replace(tzinfo=pytz.UTC),
        **kwargs,
    )


@patch("posthog.tasks.subscriptions.export_task")
@patch("posthog.tasks.subscriptions.EmailMessage")
@freeze_time("2022-02-02T08:55:00.000Z")
class TestSubscriptionsTasks(APIBaseTest):
    subscriptions: List[Subscription] = None  # type: ignore

    def setUp(self) -> None:
        insight = Insight.objects.create(team=self.team, short_id="123456", name="My Test subscription")
        set_instance_setting("EMAIL_HOST", "fake_host")
        set_instance_setting("EMAIL_ENABLED", True)

        self.subscriptions = [
            _create_insight_subscription(team=self.team, insight=insight, created_by=self.user),
            _create_insight_subscription(team=self.team, insight=insight, created_by=self.user),
            _create_insight_subscription(team=self.team, insight=insight, created_by=self.user),
            _create_insight_subscription(team=self.team, insight=insight, created_by=self.user, deleted=True),
        ]

    @patch("posthog.tasks.subscriptions.deliver_subscription_report")
    def test_subscription_delivery_scheduling(
        self, mock_deliver_task: MagicMock, MockEmailMessage: MagicMock, mock_export_task: MagicMock
    ) -> None:
        # Modify a subscription to have its target time at least an hour ahead
        self.subscriptions[2].start_date = datetime(2022, 1, 1, 10, 0).replace(tzinfo=pytz.UTC)
        self.subscriptions[2].save()
        assert self.subscriptions[2].next_delivery_date == datetime(2022, 2, 2, 10, 0).replace(tzinfo=pytz.UTC)

        schedule_all_subscriptions()

        assert mock_deliver_task.delay.mock_calls == [call(self.subscriptions[0].id), call(self.subscriptions[1].id)]

    def test_subscription_delivery(self, MockEmailMessage: MagicMock, mock_export_task: MagicMock) -> None:
        mocked_email_messages = mock_email_messages(MockEmailMessage)

        deliver_subscription_report(self.subscriptions[0].id)

        assert len(mocked_email_messages) == 2
        assert mocked_email_messages[0].send.call_count == 1
        assert "is ready!" in mocked_email_messages[0].html_body
        assert f"/exporter/export-my-test-subscription.png?token=ey" in mocked_email_messages[0].html_body

        assert mock_export_task.call_count == 1

    def test_new_subscription_delivery(self, MockEmailMessage: MagicMock, mock_export_task: MagicMock) -> None:
        mocked_email_messages = mock_email_messages(MockEmailMessage)

        deliver_new_subscription(
            self.subscriptions[0].id, new_emails=["test@posthog.com"], invite_message="My invite message"
        )

        assert len(mocked_email_messages) == 1
        assert mocked_email_messages[0].send.call_count == 1
        assert "has subscribed you" in mocked_email_messages[0].html_body
        assert "My invite message" in mocked_email_messages[0].html_body
        assert mock_export_task.call_count == 1
