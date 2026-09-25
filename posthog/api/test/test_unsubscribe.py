from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import time_machine
from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.conf import settings

from parameterized import parameterized

from products.exports.backend.models.subscription import UNSUBSCRIBE_TOKEN_EXP_DAYS, Subscription, get_unsubscribe_token
from products.product_analytics.backend.facade.models import Insight


@patch.object(settings, "JWT_SIGNING_KEY", "not-so-secret")
@time_machine.travel("2022-01-01", tick=False)
class TestUnsubscribe(APIBaseTest):
    def _create_subscription(self) -> Subscription:
        return Subscription.objects.create(
            team=self.team,
            title="My Subscription",
            insight=Insight.objects.create(team=self.team),
            target_type="email",
            target_value="test1@posthog.com,test2@posthog.com",
            frequency="weekly",
            interval=2,
            start_date=datetime(2022, 1, 1, tzinfo=ZoneInfo("UTC")),
        )

    def test_unsubscribes_with_a_valid_token(self) -> None:
        subscription = self._create_subscription()
        token = get_unsubscribe_token(subscription, "test2@posthog.com")

        response = self.client.get(f"/api/unsubscribe?token={token}")

        assert response.status_code == 200
        assert response.json() == {"success": True}
        subscription.refresh_from_db()
        assert subscription.target_value == "test1@posthog.com"

    @parameterized.expand([("no_token", ""), ("malformed_token", "?token=not-a-jwt")])
    def test_reports_failure_for_an_unusable_token(self, _name: str, query: str) -> None:
        response = self.client.get(f"/api/unsubscribe{query}")

        assert response.status_code == 200
        assert response.json() == {"success": False}

    def test_reports_failure_for_an_expired_token(self) -> None:
        token = get_unsubscribe_token(self._create_subscription(), "test2@posthog.com")

        with time_machine.travel(datetime(2022, 1, 1) + timedelta(days=UNSUBSCRIBE_TOKEN_EXP_DAYS + 1), tick=False):
            response = self.client.get(f"/api/unsubscribe?token={token}")

        assert response.status_code == 200
        assert response.json() == {"success": False}

    def test_reports_failure_when_the_subscription_no_longer_exists(self) -> None:
        subscription = self._create_subscription()
        token = get_unsubscribe_token(subscription, "test2@posthog.com")
        subscription.delete()

        response = self.client.get(f"/api/unsubscribe?token={token}")

        assert response.status_code == 200
        assert response.json() == {"success": False}
