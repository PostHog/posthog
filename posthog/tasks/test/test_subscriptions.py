from datetime import datetime
from typing import List
from unittest.mock import call, patch

import pytz
from freezegun import freeze_time

from posthog.models.insight import Insight
from posthog.models.subscription import Subscription
from posthog.tasks.subscriptions import deliver_subscription, schedule_all_subscriptions
from posthog.test.base import APIBaseTest


def _create_insight_subscription(team, insight, **kwargs):
    return Subscription.objects.create(
        team=team,
        insight=insight,
        target_type="email",
        target_value="test1@posthog.com,test2@posthog.com",
        frequency="daily",
        interval=1,
        start_date=datetime(2022, 1, 1, 9, 0).replace(tzinfo=pytz.UTC),
        **kwargs,
    )


@patch("posthog.tasks.subscriptions.export_task")
@freeze_time("2022-02-02T08:48:00.000Z")
class TestSubscriptionsTasks(APIBaseTest):
    subscriptions: List[Subscription] = None  # type: ignore

    def setUp(self) -> None:
        insight = Insight.objects.create(team=self.team, short_id="123456")
        self.subscriptions = [
            _create_insight_subscription(team=self.team, insight=insight),
            _create_insight_subscription(team=self.team, insight=insight),
            _create_insight_subscription(team=self.team, insight=insight),
        ]

    @patch("posthog.tasks.subscriptions.deliver_subscription")
    def test_subscription_delivery_scheduling(self, mock_deliver_task, mock_export_task) -> None:
        # Modify a subscription to have its target time at least an hour ahead
        self.subscriptions[2].start_date = datetime(2022, 1, 1, 10, 0).replace(tzinfo=pytz.UTC)
        self.subscriptions[2].save()
        assert self.subscriptions[2].next_delivery_date == datetime(2022, 2, 2, 10, 0).replace(tzinfo=pytz.UTC)

        schedule_all_subscriptions()

        assert mock_deliver_task.delay.mock_calls == [call(self.subscriptions[0].id), call(self.subscriptions[1].id)]

    def test_subscription_delivery(self, mock_export_task) -> None:

        deliver_subscription(self.subscriptions[0].id)

        assert mock_export_task.call_count == 1
