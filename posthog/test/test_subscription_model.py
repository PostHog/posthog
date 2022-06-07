from datetime import datetime

from posthog.models.insight import Insight
from posthog.models.subscription import Subscription
from posthog.test.base import BaseTest


class TestSubscription(BaseTest):
    def _create_insight_subscription(self, **kwargs):
        insight = Insight.objects.create(team=self.team, short_id="123456")

        return Subscription.objects.create(
            team=self.team,
            insight=insight,
            target_type="email",
            target_value="tests@posthog.com",
            frequency="weekly",
            interval=2,
            start_date=datetime(2022, 1, 1, 0, 0, 0, 0),
            **kwargs,
        )

    def test_creation(self):
        subscription = self._create_insight_subscription()
        subscription.save()

        assert subscription.title == "Sent every 2 weekly"
        subscription.set_next_delivery_date(datetime(2022, 1, 2, 0, 0, 0))
        assert subscription.next_delivery_date == datetime(2022, 1, 15, 0, 0)

    def test_update_next_delivery_date_on_update(self):
        subscription = self._create_insight_subscription()
        subscription.save()

        assert subscription.next_delivery_date >= datetime.utcnow()
