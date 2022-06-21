from datetime import datetime, timedelta
from unittest.mock import patch

import jwt
import pytest
import pytz
from django.conf import settings
from django.utils import timezone
from freezegun import freeze_time

from posthog.jwt import PosthogJwtAudience
from posthog.models.insight import Insight
from posthog.models.subscription import (
    UNSUBSCRIBE_TOKEN_EXP_DAYS,
    Subscription,
    get_unsubscribe_token,
    unsubscribe_using_token,
)
from posthog.test.base import BaseTest


@patch.object(settings, "SECRET_KEY", "not-so-secret")
@freeze_time("2022-01-01")
class TestSubscription(BaseTest):
    def _create_insight_subscription(self, **kwargs):
        insight = Insight.objects.create(team=self.team)

        params = dict(
            team=self.team,
            title="My Subscription",
            insight=insight,
            target_type="email",
            target_value="tests@posthog.com",
            frequency="weekly",
            interval=2,
            start_date=datetime(2022, 1, 1, 0, 0, 0, 0).replace(tzinfo=pytz.UTC),
        )
        params.update(**kwargs)

        return Subscription.objects.create(**params)

    def test_creation(self):
        subscription = self._create_insight_subscription()
        subscription.save()

        assert subscription.title == "My Subscription"
        subscription.set_next_delivery_date(datetime(2022, 1, 2, 0, 0, 0).replace(tzinfo=pytz.UTC))
        assert subscription.next_delivery_date == datetime(2022, 1, 15, 0, 0).replace(tzinfo=pytz.UTC)

    def test_update_next_delivery_date_on_update(self):
        subscription = self._create_insight_subscription()
        subscription.save()

        assert subscription.next_delivery_date >= timezone.now()

    def test_generating_token(self):

        subscription = self._create_insight_subscription(
            target_value="test1@posthog.com,test2@posthog.com,test3@posthog.com"
        )
        subscription.save()

        token = get_unsubscribe_token(subscription, "test2@posthog.com")
        assert token.startswith("ey")

        info = jwt.decode(token, "not-so-secret", audience=PosthogJwtAudience.UNSUBSCRIBE.value, algorithms=["HS256"])

        assert info["id"] == subscription.id
        assert info["email"] == "test2@posthog.com"
        assert info["exp"] == 1643587200

    def test_unsubscribe_using_token_succeeds(self):
        subscription = self._create_insight_subscription(
            target_value="test1@posthog.com,test2@posthog.com,test3@posthog.com"
        )
        subscription.save()

        token = get_unsubscribe_token(subscription, "test2@posthog.com")
        subscription = unsubscribe_using_token(token)
        assert subscription.target_value == "test1@posthog.com,test3@posthog.com"

    def test_unsubscribe_using_token_fails_if_too_old(self):
        subscription = self._create_insight_subscription(
            target_value="test1@posthog.com,test2@posthog.com,test3@posthog.com"
        )
        subscription.save()

        token = get_unsubscribe_token(subscription, "test2@posthog.com")

        with freeze_time(datetime(2022, 1, 1) + timedelta(days=UNSUBSCRIBE_TOKEN_EXP_DAYS + 1)):
            with pytest.raises(jwt.exceptions.ExpiredSignatureError):
                unsubscribe_using_token(token)

        with freeze_time(datetime(2022, 1, 1) + timedelta(days=UNSUBSCRIBE_TOKEN_EXP_DAYS - 1)):
            subscription = unsubscribe_using_token(token)
            assert "test2@posthog.com" not in subscription.target_value

    def test_unsubscribe_does_nothing_if_already_unsubscribed(self):
        subscription = self._create_insight_subscription(target_value="test1@posthog.com,test3@posthog.com")
        subscription.save()

        token = get_unsubscribe_token(subscription, "test2@posthog.com")

        assert subscription.target_value == "test1@posthog.com,test3@posthog.com"
        subscription = unsubscribe_using_token(token)
        assert subscription.target_value == "test1@posthog.com,test3@posthog.com"

    def test_unsubscribe_deletes_subscription_if_last_subscriber(self):
        subscription = self._create_insight_subscription(target_value="test1@posthog.com,test2@posthog.com")
        subscription.save()

        assert not subscription.deleted
        token = get_unsubscribe_token(subscription, "test1@posthog.com")
        subscription = unsubscribe_using_token(token)
        assert not subscription.deleted
        token = get_unsubscribe_token(subscription, "test2@posthog.com")
        subscription = unsubscribe_using_token(token)
        assert subscription.deleted

    def test_complex_rrule_configuration(self):
        # Equivalent to last monday and wednesday of every other month
        subscription = self._create_insight_subscription(
            interval=2, frequency="monthly", bysetpos=-1, byweekday=["wednesday", "friday"]
        )

        # Last wed or fri of 01.22 is Wed 28th
        subscription.save()
        assert subscription.next_delivery_date == datetime(2022, 1, 28, 0, 0).replace(tzinfo=pytz.UTC)
        # Last wed or fri of 01.22 is Wed 30th
        subscription.set_next_delivery_date(subscription.next_delivery_date)
        assert subscription.next_delivery_date == datetime(2022, 3, 30, 0, 0).replace(tzinfo=pytz.UTC)
        # Last wed or fri of 01.22 is Fri 27th
        subscription.set_next_delivery_date(subscription.next_delivery_date)
        assert subscription.next_delivery_date == datetime(2022, 5, 27, 0, 0).replace(tzinfo=pytz.UTC)

    def test_should_work_for_nth_days(self):
        # Equivalent to last monday and wednesday of every other month
        subscription = self._create_insight_subscription(
            interval=1,
            frequency="monthly",
            bysetpos=3,
            byweekday=["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"],
        )
        subscription.save()
        assert subscription.next_delivery_date == datetime(2022, 1, 3, 0, 0).replace(tzinfo=pytz.UTC)
        subscription.set_next_delivery_date(subscription.next_delivery_date)
        assert subscription.next_delivery_date == datetime(2022, 2, 3, 0, 0).replace(tzinfo=pytz.UTC)

    def test_should_ignore_bysetpos_if_missing_weeekday(self):
        # Equivalent to last monday and wednesday of every other month
        subscription = self._create_insight_subscription(interval=1, frequency="monthly", bysetpos=3)
        subscription.save()
        assert subscription.next_delivery_date == datetime(2022, 2, 1, 0, 0).replace(tzinfo=pytz.UTC)

    def test_subscription_summary(self):
        subscription = self._create_insight_subscription(interval=1, frequency="monthly", bysetpos=None)
        assert subscription.summary == "sent every month"
        subscription = self._create_insight_subscription(
            interval=2, frequency="monthly", byweekday=["wednesday"], bysetpos=1
        )
        assert subscription.summary == "sent every 2 months on the first Wednesday"
        subscription = self._create_insight_subscription(
            interval=1, frequency="weekly", byweekday=["wednesday"], bysetpos=-1
        )
        assert subscription.summary == "sent every week on the last Wednesday"
        subscription = self._create_insight_subscription(interval=1, frequency="weekly", byweekday=["wednesday"])
        assert subscription.summary == "sent every week"
        subscription = self._create_insight_subscription(
            interval=1,
            frequency="monthly",
            byweekday=["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"],
            bysetpos=3,
        )
        assert subscription.summary == "sent every month on the third day"

    def test_subscription_summary_with_unexpected_values(self):
        subscription = self._create_insight_subscription(
            interval=1, frequency="monthly", byweekday=["monday"], bysetpos=10,
        )
        assert subscription.summary == "sent on a schedule"
