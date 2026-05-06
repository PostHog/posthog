from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from freezegun import freeze_time
from posthog.test.base import BaseTest
from unittest.mock import patch

from django.conf import settings
from django.db import IntegrityError
from django.utils import timezone

import jwt
from parameterized import parameterized

from posthog.jwt import PosthogJwtAudience
from posthog.models.insight import Insight
from posthog.models.subscription import (
    UNSUBSCRIBE_TOKEN_EXP_DAYS,
    Subscription,
    SubscriptionDelivery,
    get_unsubscribe_token,
    unsubscribe_using_token,
)


@patch.object(settings, "SECRET_KEY", "not-so-secret")
@freeze_time("2022-01-01")
class TestSubscription(BaseTest):
    def _create_insight_subscription(self, **kwargs):
        insight = Insight.objects.create(team=self.team)

        params = {
            "team": self.team,
            "title": "My Subscription",
            "insight": insight,
            "target_type": "email",
            "target_value": "tests@posthog.com",
            "frequency": "weekly",
            "interval": 2,
            "start_date": datetime(2022, 1, 1, 0, 0, 0, 0).replace(tzinfo=ZoneInfo("UTC")),
        }
        params.update(**kwargs)

        return Subscription.objects.create(**params)

    def test_creation(self):
        subscription = self._create_insight_subscription()
        subscription.save()

        assert subscription.title == "My Subscription"
        subscription.set_next_delivery_date(datetime(2022, 1, 2, 0, 0, 0).replace(tzinfo=ZoneInfo("UTC")))
        assert subscription.next_delivery_date == datetime(2022, 1, 15, 0, 0).replace(tzinfo=ZoneInfo("UTC"))

    def test_update_next_delivery_date_on_save(self):
        subscription = self._create_insight_subscription()
        subscription.save()

        assert subscription.next_delivery_date >= timezone.now()

    def test_only_updates_next_delivery_date_if_rrule_changes(self):
        subscription = self._create_insight_subscription()
        subscription.save()
        assert subscription.next_delivery_date
        old_date = subscription.next_delivery_date

        # Change a property that does affect it
        subscription.start_date = datetime(2023, 1, 1, 0, 0, 0, 0).replace(tzinfo=ZoneInfo("UTC"))
        subscription.save()
        assert old_date != subscription.next_delivery_date
        old_date = subscription.next_delivery_date

        # Change a property that does not affect it
        subscription.title = "My new title"
        subscription.target_value = "other@example.com"
        subscription.save()
        assert old_date == subscription.next_delivery_date

    @freeze_time("2022-01-11 09:55:00")
    def test_set_next_delivery_date_when_in_upcoming_delta(self):
        subscription = Subscription.objects.create(
            id=1,
            team=self.team,
            title="Daily Subscription",
            target_type="email",
            target_value="tests@posthog.com",
            frequency="daily",
            start_date=datetime(2022, 1, 1, 10, 0, 0, 0).replace(tzinfo=ZoneInfo("UTC")),
            next_delivery_date=datetime(2022, 1, 11, 10, 0, 0, 0).replace(tzinfo=ZoneInfo("UTC")),
        )

        subscription.set_next_delivery_date(subscription.next_delivery_date)

        assert subscription.next_delivery_date == datetime(2022, 1, 12, 10, 0, 0, 0).replace(tzinfo=ZoneInfo("UTC"))

    @freeze_time("2022-01-11 09:55:00")
    def test_set_next_delivery_date_when_days_behind(self):
        subscription = Subscription.objects.create(
            id=1,
            team=self.team,
            title="Daily Subscription",
            target_type="email",
            target_value="tests@posthog.com",
            frequency="daily",
            start_date=datetime(2022, 1, 1, 10, 0, 0, 0).replace(tzinfo=ZoneInfo("UTC")),
            next_delivery_date=datetime(2022, 1, 2, 10, 0, 0, 0).replace(tzinfo=ZoneInfo("UTC")),
        )

        subscription.set_next_delivery_date(subscription.next_delivery_date)

        assert subscription.next_delivery_date == datetime(2022, 1, 12, 10, 0, 0, 0).replace(tzinfo=ZoneInfo("UTC"))

    def test_generating_token(self):
        subscription = self._create_insight_subscription(
            target_value="test1@posthog.com,test2@posthog.com,test3@posthog.com"
        )
        subscription.save()

        token = get_unsubscribe_token(subscription, "test2@posthog.com")
        assert token.startswith("ey")

        info = jwt.decode(
            token,
            "not-so-secret",
            audience=PosthogJwtAudience.UNSUBSCRIBE.value,
            algorithms=["HS256"],
        )

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
            interval=2,
            frequency="monthly",
            bysetpos=-1,
            byweekday=["wednesday", "friday"],
        )

        # Last wed or fri of 01.22 is Wed 28th
        subscription.save()
        assert subscription.next_delivery_date == datetime(2022, 1, 28, 0, 0).replace(tzinfo=ZoneInfo("UTC"))
        # Last wed or fri of 01.22 is Wed 30th
        subscription.set_next_delivery_date(subscription.next_delivery_date)
        assert subscription.next_delivery_date == datetime(2022, 3, 30, 0, 0).replace(tzinfo=ZoneInfo("UTC"))
        # Last wed or fri of 01.22 is Fri 27th
        subscription.set_next_delivery_date(subscription.next_delivery_date)
        assert subscription.next_delivery_date == datetime(2022, 5, 27, 0, 0).replace(tzinfo=ZoneInfo("UTC"))

    def test_should_work_for_nth_days(self):
        # Equivalent to last monday and wednesday of every other month
        subscription = self._create_insight_subscription(
            interval=1,
            frequency="monthly",
            bysetpos=3,
            byweekday=[
                "monday",
                "tuesday",
                "wednesday",
                "thursday",
                "friday",
                "saturday",
                "sunday",
            ],
        )
        subscription.save()
        assert subscription.next_delivery_date == datetime(2022, 1, 3, 0, 0).replace(tzinfo=ZoneInfo("UTC"))
        subscription.set_next_delivery_date(subscription.next_delivery_date)
        assert subscription.next_delivery_date == datetime(2022, 2, 3, 0, 0).replace(tzinfo=ZoneInfo("UTC"))

    def test_should_ignore_bysetpos_if_missing_weeekday(self):
        # Equivalent to last monday and wednesday of every other month
        subscription = self._create_insight_subscription(interval=1, frequency="monthly", bysetpos=3)
        subscription.save()
        assert subscription.next_delivery_date == datetime(2022, 2, 1, 0, 0).replace(tzinfo=ZoneInfo("UTC"))

    @parameterized.expand(
        [
            ("monthly_no_bysetpos", {"interval": 1, "frequency": "monthly", "bysetpos": None}, "sent every month"),
            (
                "bimonthly_first_wednesday",
                {"interval": 2, "frequency": "monthly", "byweekday": ["wednesday"], "bysetpos": 1},
                "sent every 2 months on the first Wednesday",
            ),
            (
                "weekly_last_wednesday",
                {"interval": 1, "frequency": "weekly", "byweekday": ["wednesday"], "bysetpos": -1},
                "sent every week on the last Wednesday",
            ),
            (
                "weekly_wednesday_no_bysetpos",
                {"interval": 1, "frequency": "weekly", "byweekday": ["wednesday"]},
                "sent every week",
            ),
            (
                "monthly_third_day",
                {
                    "interval": 1,
                    "frequency": "monthly",
                    "byweekday": ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"],
                    "bysetpos": 3,
                },
                "sent every month on the third day",
            ),
            (
                "unexpected_bysetpos_fallback",
                {"interval": 1, "frequency": "monthly", "byweekday": ["monday"], "bysetpos": 10},
                "sent on a schedule",
            ),
        ]
    )
    def test_subscription_summary(self, _name, params, expected_summary):
        subscription = self._create_insight_subscription(**params)
        assert subscription.summary == expected_summary

    @parameterized.expand(
        [
            ("first_weekday", 1, "sent every month on the first weekday"),
            ("second_weekday", 2, "sent every month on the second weekday"),
            ("third_weekday", 3, "sent every month on the third weekday"),
            ("fourth_weekday", 4, "sent every month on the fourth weekday"),
            ("last_weekday", -1, "sent every month on the last weekday"),
            ("no_bysetpos", None, "sent every month"),
        ]
    )
    def test_subscription_summary_weekday(self, _name, bysetpos, expected_summary):
        subscription = self._create_insight_subscription(
            interval=1,
            frequency="monthly",
            byweekday=["monday", "tuesday", "wednesday", "thursday", "friday"],
            bysetpos=bysetpos,
        )
        assert subscription.summary == expected_summary

    def test_subscription_delivery_creation(self):
        subscription = self._create_insight_subscription()

        delivery = SubscriptionDelivery.objects.create(
            subscription=subscription,
            team=self.team,
            temporal_workflow_id="process-subscription-1",
            idempotency_key="test-key-1",
            trigger_type="scheduled",
            target_type=subscription.target_type,
            target_value=subscription.target_value,
            status=SubscriptionDelivery.Status.STARTING,
        )

        assert delivery.status == "starting"
        assert delivery.subscription == subscription
        assert delivery.error is None
        assert delivery.recipient_results == []
        assert delivery.exported_asset_ids == []
        assert delivery.finished_at is None

    def test_duplicate_idempotency_key_raises(self):
        subscription = self._create_insight_subscription()

        SubscriptionDelivery.objects.create(
            subscription=subscription,
            team=self.team,
            temporal_workflow_id="process-subscription-1",
            idempotency_key="same-key",
            trigger_type="scheduled",
            target_type="email",
            target_value="test@posthog.com",
        )

        with pytest.raises(IntegrityError):
            SubscriptionDelivery.objects.create(
                subscription=subscription,
                team=self.team,
                temporal_workflow_id="process-subscription-1",
                idempotency_key="same-key",
                trigger_type="scheduled",
                target_type="email",
                target_value="test@posthog.com",
            )

    def test_distinct_idempotency_keys_create_two_rows(self):
        subscription = self._create_insight_subscription()

        SubscriptionDelivery.objects.create(
            subscription=subscription,
            team=self.team,
            temporal_workflow_id="process-subscription-1",
            idempotency_key="key-run-1",
            trigger_type="scheduled",
            target_type="email",
            target_value="test@posthog.com",
        )

        second = SubscriptionDelivery.objects.create(
            subscription=subscription,
            team=self.team,
            temporal_workflow_id="process-subscription-1",
            idempotency_key="key-run-2",
            trigger_type="scheduled",
            target_type="email",
            target_value="test@posthog.com",
        )
        first = SubscriptionDelivery.objects.get(idempotency_key="key-run-1")
        assert first.id != second.id
        assert SubscriptionDelivery.objects.filter(subscription=subscription).count() == 2

    def test_subscription_delivery_get_or_create_idempotency(self):
        subscription = self._create_insight_subscription()

        delivery1, created1 = SubscriptionDelivery.objects.get_or_create(
            idempotency_key="idem-key",
            defaults={
                "subscription": subscription,
                "team": self.team,
                "temporal_workflow_id": "wf-1",
                "trigger_type": "scheduled",
                "target_type": "email",
                "target_value": "test@posthog.com",
            },
        )
        delivery2, created2 = SubscriptionDelivery.objects.get_or_create(
            idempotency_key="idem-key",
            defaults={
                "subscription": subscription,
                "team": self.team,
                "temporal_workflow_id": "wf-1",
                "trigger_type": "scheduled",
                "target_type": "email",
                "target_value": "test@posthog.com",
            },
        )

        assert created1 is True
        assert created2 is False
        assert delivery1.id == delivery2.id

    def test_subscription_delivery_cascades_on_subscription_delete(self):
        subscription = self._create_insight_subscription()
        SubscriptionDelivery.objects.create(
            subscription=subscription,
            team=self.team,
            temporal_workflow_id="wf-1",
            idempotency_key="cascade-key",
            trigger_type="scheduled",
            target_type="email",
            target_value="test@posthog.com",
        )

        assert SubscriptionDelivery.objects.count() == 1
        subscription.insight.delete()  # cascades to subscription, then to delivery
        assert SubscriptionDelivery.objects.count() == 0

    @parameterized.expand(
        [
            # First weekday of month — Jan 1 is Saturday, so first weekday is Mon Jan 3
            ("first_weekday_sat_start", "2022-01-01", 1, datetime(2022, 1, 3, 9, 0, tzinfo=ZoneInfo("UTC"))),
            # First weekday of month starting on Sunday
            ("first_weekday_sun_start", "2022-05-01", 1, datetime(2022, 5, 2, 9, 0, tzinfo=ZoneInfo("UTC"))),
            # Last weekday of month ending on Saturday
            ("last_weekday_sat_end", "2022-07-01", -1, datetime(2022, 7, 29, 9, 0, tzinfo=ZoneInfo("UTC"))),
            # Second weekday
            ("second_weekday", "2022-01-01", 2, datetime(2022, 1, 4, 9, 0, tzinfo=ZoneInfo("UTC"))),
            # Last weekday of Feb in leap year (Feb 29 2024 is Thursday)
            ("last_weekday_feb_leap", "2024-02-01", -1, datetime(2024, 2, 29, 9, 0, tzinfo=ZoneInfo("UTC"))),
            # First weekday when month starts on a weekday (Mar 1 2022 is Tuesday)
            ("first_weekday_starts_on_weekday", "2022-03-01", 1, datetime(2022, 3, 1, 9, 0, tzinfo=ZoneInfo("UTC"))),
            # Last weekday when month ends on a weekday (Jun 30 2022 is Thursday)
            ("last_weekday_ends_on_weekday", "2022-06-01", -1, datetime(2022, 6, 30, 9, 0, tzinfo=ZoneInfo("UTC"))),
            # Fourth weekday (Jan 2022: Mon 3, Tue 4, Wed 5, Thu 6)
            ("fourth_weekday", "2022-01-01", 4, datetime(2022, 1, 6, 9, 0, tzinfo=ZoneInfo("UTC"))),
            # Last weekday of Feb in non-leap year (Feb 28 2022 is Monday)
            ("last_weekday_feb_non_leap", "2022-02-01", -1, datetime(2022, 2, 28, 9, 0, tzinfo=ZoneInfo("UTC"))),
        ]
    )
    def test_weekday_rrule_edge_cases(self, _name, freeze_date, bysetpos, expected_next):
        with freeze_time(freeze_date):
            subscription = self._create_insight_subscription(
                interval=1,
                frequency="monthly",
                byweekday=["monday", "tuesday", "wednesday", "thursday", "friday"],
                bysetpos=bysetpos,
                start_date=datetime(2021, 1, 1, 9, 0, tzinfo=ZoneInfo("UTC")),
            )
            subscription.set_next_delivery_date()
            assert subscription.next_delivery_date == expected_next
