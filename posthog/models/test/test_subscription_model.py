from collections.abc import Callable
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
import time_machine
from posthog.test.base import BaseTest
from unittest.mock import patch

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

import jwt
from parameterized import parameterized

from posthog.constants import AvailableFeature
from posthog.event_usage import EventSource
from posthog.jwt import PosthogJwtAudience

from products.dashboards.backend.models.dashboard import Dashboard
from products.exports.backend.models.subscription import (
    SUBSCRIPTION_COUNT_ALLOWED_ON_FREE_TIER,
    UNSUBSCRIBE_TOKEN_EXP_DAYS,
    Subscription,
    SubscriptionDelivery,
    attribute_subscription_saves,
    get_unsubscribe_token,
    unsubscribe_using_token,
)
from products.product_analytics.backend.facade.models import Insight


class TestSubscriptionScheduling:
    def test_weekly_schedule_ignores_stale_monthly_position(self) -> None:
        subscription = Subscription(
            frequency=Subscription.SubscriptionFrequency.WEEKLY,
            interval=1,
            start_date=datetime(2026, 8, 3, 9, tzinfo=ZoneInfo("UTC")),
            byweekday=["monday", "wednesday", "friday"],
            bysetpos=1,
        )

        assert subscription.summary == "sent every week on Monday, Wednesday and Friday"
        assert subscription.rrule[0] == datetime(2026, 8, 3, 9, tzinfo=ZoneInfo("UTC"))
        assert subscription.rrule[1] == datetime(2026, 8, 5, 9, tzinfo=ZoneInfo("UTC"))
        assert subscription.rrule[2] == datetime(2026, 8, 7, 9, tzinfo=ZoneInfo("UTC"))

    @parameterized.expand(
        [
            (
                "daily_weekdays",
                "daily",
                ["monday", "tuesday", "wednesday", "thursday", "friday"],
                datetime(2024, 1, 5, 9, 0, tzinfo=ZoneInfo("UTC")),
                datetime(2024, 1, 8, 9, 0, tzinfo=ZoneInfo("UTC")),
            ),
            (
                "weekly_multiple_days",
                "weekly",
                ["wednesday", "friday"],
                datetime(2024, 1, 1, 9, 0, tzinfo=ZoneInfo("UTC")),
                datetime(2024, 1, 3, 9, 0, tzinfo=ZoneInfo("UTC")),
            ),
        ]
    )
    @time_machine.travel("2024-01-01 08:00:00", tick=False)
    def test_selected_weekdays_control_delivery_dates(
        self,
        _name: str,
        frequency: str,
        byweekday: list[str],
        from_dt: datetime,
        expected_next_delivery: datetime,
    ) -> None:
        next_delivery_date = Subscription._compute_next_delivery_date(
            frequency=frequency,
            interval=1,
            start_date=datetime(2024, 1, 1, 9, 0, tzinfo=ZoneInfo("UTC")),
            from_dt=from_dt,
            byweekday=byweekday,
        )

        assert next_delivery_date == expected_next_delivery

    @time_machine.travel("2024-01-01 08:00:00", tick=False)
    def test_daily_interval_without_a_possible_weekday_returns_none(self) -> None:
        next_delivery_date = Subscription._compute_next_delivery_date(
            frequency="daily",
            interval=7,
            start_date=datetime(2024, 1, 1, 9, 0, tzinfo=ZoneInfo("UTC")),
            byweekday=["tuesday"],
        )

        assert next_delivery_date is None

    @time_machine.travel("2026-10-25 11:00:00", tick=False)
    def test_weekly_delivery_keeps_local_wall_time_across_fall_dst_transition(self) -> None:
        # #42016: a weekly Monday 8am US/Central subscription created in summer is stored
        # as 13:00 UTC (CDT). After the Nov 1 transition to CST it must still deliver at
        # 8am local, i.e. 14:00 UTC, not drift to 7am.
        start = datetime(2026, 6, 1, 13, 0, tzinfo=ZoneInfo("UTC"))
        kwargs = {
            "frequency": "weekly",
            "interval": 1,
            "start_date": start,
            "byweekday": ["monday"],
            "tz_name": "US/Central",
        }

        before = Subscription._compute_next_delivery_date(
            from_dt=datetime(2026, 10, 25, 12, 0, tzinfo=ZoneInfo("UTC")), **kwargs
        )
        assert before == datetime(2026, 10, 26, 13, 0, tzinfo=ZoneInfo("UTC"))  # Mon 8am CDT

        after = Subscription._compute_next_delivery_date(
            from_dt=datetime(2026, 11, 10, 12, 0, tzinfo=ZoneInfo("UTC")), **kwargs
        )
        assert after == datetime(2026, 11, 16, 14, 0, tzinfo=ZoneInfo("UTC"))  # Mon 8am CST

    @time_machine.travel("2027-02-20 11:00:00", tick=False)
    def test_weekly_delivery_keeps_local_wall_time_across_spring_forward(self) -> None:
        # 8am US/Central in winter is 14:00 UTC (CST); after the Mar 14, 2027 transition
        # it must become 13:00 UTC (CDT).
        start = datetime(2027, 1, 4, 14, 0, tzinfo=ZoneInfo("UTC"))
        kwargs = {
            "frequency": "weekly",
            "interval": 1,
            "start_date": start,
            "byweekday": ["monday"],
            "tz_name": "US/Central",
        }

        before = Subscription._compute_next_delivery_date(
            from_dt=datetime(2027, 2, 20, 12, 0, tzinfo=ZoneInfo("UTC")), **kwargs
        )
        assert before == datetime(2027, 2, 22, 14, 0, tzinfo=ZoneInfo("UTC"))  # Mon 8am CST

        after = Subscription._compute_next_delivery_date(
            from_dt=datetime(2027, 3, 15, 0, 0, tzinfo=ZoneInfo("UTC")), **kwargs
        )
        assert after == datetime(2027, 3, 15, 13, 0, tzinfo=ZoneInfo("UTC"))  # Mon 8am CDT

    @time_machine.travel("2024-01-01 09:00:00", tick=False)
    def test_daily_delivery_in_half_hour_offset_timezone_without_dst(self) -> None:
        # 9am Asia/Kolkata daily: no DST, so the UTC time must stay fixed at 03:30.
        next_delivery_date = Subscription._compute_next_delivery_date(
            frequency="daily",
            interval=1,
            start_date=datetime(2024, 1, 1, 3, 30, tzinfo=ZoneInfo("UTC")),
            from_dt=datetime(2024, 1, 1, 10, 0, tzinfo=ZoneInfo("UTC")),
            tz_name="Asia/Kolkata",
        )

        assert next_delivery_date == datetime(2024, 1, 2, 3, 30, tzinfo=ZoneInfo("UTC"))

    @time_machine.travel("2026-11-10 11:00:00", tick=False)
    def test_without_timezone_the_utc_anchored_behavior_is_kept(self) -> None:
        # tz_name=None (or an unknown name) reproduces the pre-fix behavior exactly:
        # the delivery stays at a fixed UTC time and drifts in local time after DST.
        kwargs = {
            "frequency": "weekly",
            "interval": 1,
            "start_date": datetime(2026, 6, 1, 13, 0, tzinfo=ZoneInfo("UTC")),
            "byweekday": ["monday"],
        }
        from_dt = datetime(2026, 11, 10, 12, 0, tzinfo=ZoneInfo("UTC"))
        expected = datetime(2026, 11, 16, 13, 0, tzinfo=ZoneInfo("UTC"))

        assert Subscription._compute_next_delivery_date(from_dt=from_dt, **kwargs) == expected
        assert Subscription._compute_next_delivery_date(from_dt=from_dt, tz_name="not-a-timezone", **kwargs) == expected

    @time_machine.travel("2026-09-06 23:00:00", tick=False)
    def test_weekday_guard_matches_the_local_weekday(self) -> None:
        # Monday 8am Asia/Tokyo is stored as Sunday 23:00 UTC. The daily/7 weekday guard
        # must accept byweekday=["monday"] because Monday is the local weekday.
        next_delivery_date = Subscription._compute_next_delivery_date(
            frequency="daily",
            interval=7,
            start_date=datetime(2026, 9, 6, 23, 0, tzinfo=ZoneInfo("UTC")),  # Mon 8am JST
            from_dt=datetime(2026, 9, 7, 0, 0, tzinfo=ZoneInfo("UTC")),
            byweekday=["monday"],
            tz_name="Asia/Tokyo",
        )

        assert next_delivery_date == datetime(2026, 9, 13, 23, 0, tzinfo=ZoneInfo("UTC"))  # Mon Sep 14 8am JST

    @time_machine.travel("2026-10-31 11:00:00", tick=False)
    def test_ambiguous_local_time_resolves_to_the_earlier_occurrence(self) -> None:
        # Daily 1:30am US/Central: on Nov 1 2026 the wall time happens twice (CDT, then CST).
        # zoneinfo fold=0 picks the earlier occurrence: 1:30am CDT = 06:30 UTC.
        next_delivery_date = Subscription._compute_next_delivery_date(
            frequency="daily",
            interval=1,
            start_date=datetime(2026, 10, 20, 6, 30, tzinfo=ZoneInfo("UTC")),
            from_dt=datetime(2026, 10, 31, 12, 0, tzinfo=ZoneInfo("UTC")),
            tz_name="US/Central",
        )

        assert next_delivery_date == datetime(2026, 11, 1, 6, 30, tzinfo=ZoneInfo("UTC"))

    @time_machine.travel("2027-03-13 11:00:00", tick=False)
    def test_nonexistent_local_time_normalizes_forward(self) -> None:
        # Daily 2:30am US/Central: on Mar 14 2027 that wall time never happens (spring
        # forward 02:00 -> 03:00). The pre-transition offset applies, so the delivery lands
        # at 08:30 UTC, i.e. 3:30am local once the clock jumps.
        next_delivery_date = Subscription._compute_next_delivery_date(
            frequency="daily",
            interval=1,
            start_date=datetime(2027, 3, 1, 8, 30, tzinfo=ZoneInfo("UTC")),
            from_dt=datetime(2027, 3, 13, 12, 0, tzinfo=ZoneInfo("UTC")),
            tz_name="US/Central",
        )

        assert next_delivery_date == datetime(2027, 3, 14, 8, 30, tzinfo=ZoneInfo("UTC"))

    @time_machine.travel("2026-11-01 05:15:00", tick=False)
    def test_first_fold_occurrence_is_returned_while_it_is_still_ahead(self) -> None:
        # Daily 1:30am US/Central, computed at 1:15am CDT (06:15 UTC) on transition day:
        # the first 1:30am of the day is still ahead, so it is the next delivery.
        next_delivery_date = Subscription._compute_next_delivery_date(
            frequency="daily",
            interval=1,
            start_date=datetime(2026, 10, 20, 6, 30, tzinfo=ZoneInfo("UTC")),
            from_dt=datetime(2026, 11, 1, 6, 15, tzinfo=ZoneInfo("UTC")),
            tz_name="US/Central",
        )

        assert next_delivery_date == datetime(2026, 11, 1, 6, 30, tzinfo=ZoneInfo("UTC"))

    @time_machine.travel("2026-11-01 06:15:00", tick=False)
    def test_second_fold_occurrence_is_returned_when_the_first_is_already_past(self) -> None:
        # Same schedule computed during the repeated hour, at 1:15am CST (07:15 UTC):
        # the first 1:30am (06:30 UTC) is already past, so the delivery is the second
        # occurrence of that wall time: 1:30am CST = 07:30 UTC.
        next_delivery_date = Subscription._compute_next_delivery_date(
            frequency="daily",
            interval=1,
            start_date=datetime(2026, 10, 20, 6, 30, tzinfo=ZoneInfo("UTC")),
            from_dt=datetime(2026, 11, 1, 7, 15, tzinfo=ZoneInfo("UTC")),
            tz_name="US/Central",
        )

        assert next_delivery_date == datetime(2026, 11, 1, 7, 30, tzinfo=ZoneInfo("UTC"))

    @time_machine.travel("2026-11-01 05:45:00", tick=False)
    def test_second_fold_is_returned_once_the_first_fold_wall_time_has_passed(self) -> None:
        # At 1:45am CDT (06:45 UTC) the 1:30 wall time is behind on the wall clock, but its
        # second occurrence (1:30am CST = 07:30 UTC) is still ahead.
        next_delivery_date = Subscription._compute_next_delivery_date(
            frequency="daily",
            interval=1,
            start_date=datetime(2026, 10, 20, 6, 30, tzinfo=ZoneInfo("UTC")),
            from_dt=datetime(2026, 11, 1, 6, 45, tzinfo=ZoneInfo("UTC")),
            tz_name="US/Central",
        )

        assert next_delivery_date == datetime(2026, 11, 1, 7, 30, tzinfo=ZoneInfo("UTC"))

    @time_machine.travel("2026-11-01 05:30:00", tick=False)
    def test_an_exact_occurrence_instant_counts_as_already_past(self) -> None:
        # Exactly at the first-fold 1:30am (06:30 UTC): strictly-after semantics move to the
        # second occurrence at 1:30am CST (07:30 UTC).
        next_delivery_date = Subscription._compute_next_delivery_date(
            frequency="daily",
            interval=1,
            start_date=datetime(2026, 10, 20, 6, 30, tzinfo=ZoneInfo("UTC")),
            from_dt=datetime(2026, 11, 1, 6, 30, tzinfo=ZoneInfo("UTC")),
            tz_name="US/Central",
        )

        assert next_delivery_date == datetime(2026, 11, 1, 7, 30, tzinfo=ZoneInfo("UTC"))

    @time_machine.travel("2027-04-03 13:50:00", tick=False)
    def test_half_hour_backward_transition(self) -> None:
        # Australia/Lord_Howe falls back 30 minutes on Apr 4 2027: daily 1:45am exists at
        # 14:45 UTC (+11) and 15:15 UTC (+10:30). At 14:50 UTC only the second is ahead.
        next_delivery_date = Subscription._compute_next_delivery_date(
            frequency="daily",
            interval=1,
            start_date=datetime(2027, 3, 20, 14, 45, tzinfo=ZoneInfo("UTC")),
            from_dt=datetime(2027, 4, 3, 14, 50, tzinfo=ZoneInfo("UTC")),
            tz_name="Australia/Lord_Howe",
        )

        assert next_delivery_date == datetime(2027, 4, 3, 15, 15, tzinfo=ZoneInfo("UTC"))

    @time_machine.travel("2026-10-03 11:00:00", tick=False)
    def test_daily_delivery_keeps_early_wall_time_across_positive_offset_transition(self) -> None:
        # Daily 1:00am Australia/Sydney: on the Oct 4 spring-forward day (02:00 -> 03:00)
        # 1:00am still exists, ahead of the gap, so the delivery is 15:00 UTC Oct 3 with
        # the pre-transition offset. The next day it moves to 14:00 UTC (+11).
        kwargs = {
            "frequency": "daily",
            "interval": 1,
            "start_date": datetime(2026, 9, 1, 15, 0, tzinfo=ZoneInfo("UTC")),
            "tz_name": "Australia/Sydney",
        }

        on_transition_day = Subscription._compute_next_delivery_date(
            from_dt=datetime(2026, 10, 3, 12, 0, tzinfo=ZoneInfo("UTC")), **kwargs
        )
        assert on_transition_day == datetime(2026, 10, 3, 15, 0, tzinfo=ZoneInfo("UTC"))

        after = Subscription._compute_next_delivery_date(
            from_dt=datetime(2026, 10, 4, 12, 0, tzinfo=ZoneInfo("UTC")), **kwargs
        )
        assert after == datetime(2026, 10, 4, 14, 0, tzinfo=ZoneInfo("UTC"))

    @time_machine.travel("2026-10-03 11:00:00", tick=False)
    def test_half_hour_forward_transition_keeps_early_wall_time(self) -> None:
        # Daily 12:15am Australia/Lord_Howe: the Oct 4 spring forward (02:00 -> 02:30)
        # leaves 12:15am intact at 13:45 UTC (+10:30); the next day is 13:15 UTC (+11).
        kwargs = {
            "frequency": "daily",
            "interval": 1,
            "start_date": datetime(2026, 9, 1, 13, 45, tzinfo=ZoneInfo("UTC")),
            "tz_name": "Australia/Lord_Howe",
        }

        on_transition_day = Subscription._compute_next_delivery_date(
            from_dt=datetime(2026, 10, 3, 12, 0, tzinfo=ZoneInfo("UTC")), **kwargs
        )
        assert on_transition_day == datetime(2026, 10, 3, 13, 45, tzinfo=ZoneInfo("UTC"))

        after = Subscription._compute_next_delivery_date(
            from_dt=datetime(2026, 10, 4, 12, 0, tzinfo=ZoneInfo("UTC")), **kwargs
        )
        assert after == datetime(2026, 10, 4, 13, 15, tzinfo=ZoneInfo("UTC"))

    @time_machine.travel("2026-10-24 22:00:00", tick=False)
    def test_two_hour_fold_returns_both_occurrences(self) -> None:
        # Antarctica/Troll falls back two hours on Oct 25 2026 (03:00 -> 01:00), so daily
        # 2:00am exists at 00:00 UTC (+2) and again at 02:00 UTC (+0). Both folds are
        # returned earliest-first while they are still ahead; the next day uses +0.
        kwargs = {
            "frequency": "daily",
            "interval": 1,
            "start_date": datetime(2026, 10, 20, 0, 0, tzinfo=ZoneInfo("UTC")),
            "tz_name": "Antarctica/Troll",
        }

        before = Subscription._compute_next_delivery_date(
            from_dt=datetime(2026, 10, 24, 23, 0, tzinfo=ZoneInfo("UTC")), **kwargs
        )
        assert before == datetime(2026, 10, 25, 0, 0, tzinfo=ZoneInfo("UTC"))

        between = Subscription._compute_next_delivery_date(
            from_dt=datetime(2026, 10, 25, 0, 30, tzinfo=ZoneInfo("UTC")), **kwargs
        )
        assert between == datetime(2026, 10, 25, 2, 0, tzinfo=ZoneInfo("UTC"))

        after = Subscription._compute_next_delivery_date(
            from_dt=datetime(2026, 10, 25, 2, 30, tzinfo=ZoneInfo("UTC")), **kwargs
        )
        assert after == datetime(2026, 10, 26, 2, 0, tzinfo=ZoneInfo("UTC"))

    @time_machine.travel("2026-10-15 12:44:00", tick=False)
    def test_subsecond_start_date_uses_whole_second_occurrences(self) -> None:
        # dateutil's rrule works at whole-second precision: a 9:00:00.500 start produces
        # 9:00:00 occurrences. The frontend preview mirrors this, so both stacks agree on
        # the strict-future boundary at second precision.
        kwargs = {
            "frequency": "daily",
            "interval": 1,
            "start_date": datetime(2026, 9, 1, 13, 0, 0, 500000, tzinfo=ZoneInfo("UTC")),
            "tz_name": "America/New_York",
        }
        occurrence = datetime(2026, 10, 15, 13, 0, tzinfo=ZoneInfo("UTC"))  # 9am EDT

        before = Subscription._compute_next_delivery_date(from_dt=occurrence - timedelta(milliseconds=50), **kwargs)
        assert before == occurrence

        exact = Subscription._compute_next_delivery_date(from_dt=occurrence, **kwargs)
        assert exact == occurrence + timedelta(days=1)

        after = Subscription._compute_next_delivery_date(from_dt=occurrence + timedelta(milliseconds=50), **kwargs)
        assert after == occurrence + timedelta(days=1)

    @time_machine.travel("1920-04-30 11:45:00", tick=False)
    def test_second_precision_historical_offset_transition(self) -> None:
        # America/Argentina/Catamarca sprang forward 16m48s on May 1 1920 (00:00 ->
        # 00:16:48), so daily 00:01:20 never happens that day: it delivers at the
        # pre-transition offset, 04:18:08 UTC.
        next_delivery_date = Subscription._compute_next_delivery_date(
            frequency="daily",
            interval=1,
            start_date=datetime(1920, 4, 29, 4, 18, 8, tzinfo=ZoneInfo("UTC")),
            from_dt=datetime(1920, 4, 30, 12, 0, tzinfo=ZoneInfo("UTC")),
            tz_name="America/Argentina/Catamarca",
        )

        assert next_delivery_date == datetime(1920, 5, 1, 4, 18, 8, tzinfo=ZoneInfo("UTC"))

    @time_machine.travel("1921-12-31 11:45:00", tick=False)
    def test_sub_minute_historical_gap(self) -> None:
        # America/Bahia_Banderas sprang forward 60 seconds on Jan 1 1922 (23:59 -> 00:00):
        # daily 23:59:30 never happens, delivering at the pre-transition offset.
        next_delivery_date = Subscription._compute_next_delivery_date(
            frequency="daily",
            interval=1,
            start_date=datetime(1921, 12, 30, 7, 0, 30, tzinfo=ZoneInfo("UTC")),
            from_dt=datetime(1921, 12, 31, 12, 0, tzinfo=ZoneInfo("UTC")),
            tz_name="America/Bahia_Banderas",
        )

        assert next_delivery_date == datetime(1922, 1, 1, 7, 0, 30, tzinfo=ZoneInfo("UTC"))


class TestSubscriptionDeliveryConfig:
    @parameterized.expand(
        [
            ("omitted_option", {}, "include_feedback", True),
            ("malformed_config", "invalid", "include_images", True),
            ("enabled_option", {"include_manage_link": True}, "include_manage_link", True),
            ("disabled_option", {"include_manage_link": False}, "include_manage_link", False),
        ]
    )
    def test_includes_delivery_part(self, _name: str, delivery_config, option: str, expected: bool) -> None:
        subscription = Subscription(
            delivery_config=delivery_config,
            frequency=Subscription.SubscriptionFrequency.WEEKLY,
            interval=1,
            start_date=datetime(2026, 1, 1, tzinfo=ZoneInfo("UTC")),
        )

        assert subscription.includes_delivery_part(option) is expected


@patch.object(settings, "JWT_SIGNING_KEY", "not-so-secret")
@time_machine.travel("2022-01-01", tick=False)
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

    def test_save_computes_next_delivery_in_the_team_timezone(self):
        # set_next_delivery_date must forward the team timezone so the saved
        # next_delivery_date follows the local wall time across DST (#42016):
        # a weekly Monday 8am US/Central subscription created in summer delivers at
        # 14:00 UTC in winter, not 13:00 UTC.
        self.team.timezone = "US/Central"
        self.team.save()

        subscription = self._create_insight_subscription(
            frequency="weekly",
            interval=1,
            start_date=datetime(2021, 6, 7, 13, 0, tzinfo=ZoneInfo("UTC")),  # Monday 8am CDT
            byweekday=["monday"],
        )

        # Frozen at 2022-01-01: the next Monday is Jan 3, 8am CST = 14:00 UTC.
        assert subscription.next_delivery_date == datetime(2022, 1, 3, 14, 0, tzinfo=ZoneInfo("UTC"))

    def test_creation(self):
        subscription = self._create_insight_subscription()
        subscription.save()

        assert subscription.title == "My Subscription"
        subscription.set_next_delivery_date(datetime(2022, 1, 2, 0, 0, 0).replace(tzinfo=ZoneInfo("UTC")))
        assert subscription.next_delivery_date == datetime(2022, 1, 15, 0, 0).replace(tzinfo=ZoneInfo("UTC"))

    def _create_subscription(self, **kwargs) -> Subscription:
        return Subscription.objects.create(
            team=self.team,
            target_type="email",
            target_value="tests@posthog.com",
            frequency="weekly",
            interval=1,
            start_date=datetime(2022, 1, 1, tzinfo=ZoneInfo("UTC")),
            **kwargs,
        )

    def test_analytics_event_runs_after_the_subscription_transaction_commits(self) -> None:
        with (
            patch("posthog.event_usage.posthoganalytics.capture") as mock_capture,
            self.captureOnCommitCallbacks(execute=True),
            attribute_subscription_saves({"source": EventSource.WEB}),
        ):
            with transaction.atomic():
                self._create_subscription(
                    prompt="Summarize signups",
                    title="Weekly AI digest",
                    created_by=self.user,
                )
                mock_capture.assert_not_called()

        mock_capture.assert_called_once()
        assert mock_capture.call_args.kwargs["properties"]["source"] == EventSource.WEB

    @parameterized.expand(
        [
            (
                "insight_relation",
                lambda self: self._create_subscription(insight=Insight.objects.create(team=self.team)),
                Subscription.ResourceType.INSIGHT,
            ),
            (
                "dashboard_relation",
                lambda self: self._create_subscription(dashboard=Dashboard.objects.create(team=self.team)),
                Subscription.ResourceType.DASHBOARD,
            ),
            (
                "prompt_no_relation",
                lambda self: self._create_subscription(prompt="Summarize signups"),
                Subscription.ResourceType.AI_PROMPT,
            ),
        ]
    )
    def test_resource_type_derived_from_relation(
        self, _name: str, make_subscription: Callable[..., Subscription], expected: "Subscription.ResourceType"
    ):
        subscription = make_subscription(self)

        assert subscription.resource_type == expected
        subscription.refresh_from_db()
        assert subscription.resource_type == expected

    def test_resource_type_raises_without_relation(self):
        subscription = self._create_subscription()
        with self.assertRaises(ValueError):
            _ = subscription.resource_type

    def test_analytics_metadata_includes_insight_query_kind(self):
        insight = Insight.objects.create(
            team=self.team,
            query={"kind": "InsightVizNode", "source": {"kind": "TrendsQuery", "series": []}},
        )
        metadata = self._create_subscription(insight=insight).get_analytics_metadata()

        assert metadata["query_kind"] == "InsightVizNode"
        assert metadata["query_source_kind"] == "TrendsQuery"

    def test_analytics_metadata_omits_query_kind_for_non_insight_subscription(self):
        # Query-kind attribution is insight-only; dashboard/prompt subs must not carry stale keys.
        metadata = self._create_subscription(
            dashboard=Dashboard.objects.create(team=self.team)
        ).get_analytics_metadata()

        assert "query_kind" not in metadata
        assert "query_source_kind" not in metadata

    @parameterized.expand(
        [
            ("insight", 1, None, None, Subscription.ResourceType.INSIGHT),
            ("dashboard", None, 2, None, Subscription.ResourceType.DASHBOARD),
            ("prompt", None, None, "Summarize signups", Subscription.ResourceType.AI_PROMPT),
            ("insight_takes_precedence", 1, 2, "ignored", Subscription.ResourceType.INSIGHT),
        ]
    )
    def test_derive_resource_type(
        self, _name: str, insight_id: int | None, dashboard_id: int | None, prompt: str | None, expected: str
    ):
        assert Subscription.derive_resource_type(insight_id, dashboard_id, prompt) == expected

    @parameterized.expand([("all_none", None), ("empty_prompt", "")])
    def test_derive_resource_type_raises_when_relationless(self, _name: str, prompt: str | None):
        with pytest.raises(ValueError, match="no insight, dashboard, or prompt"):
            Subscription.derive_resource_type(None, None, prompt)

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

    @parameterized.expand(
        [
            ("enabling_images_clears_plan", {"include_images": False}, {"include_images": True}, False),
            ("images_already_enabled_keeps_plan", {"include_images": True}, {"include_images": True}, True),
        ]
    )
    def test_deferred_delivery_config_preserves_plan_invalidation_state(
        self, _name: str, initial_config: dict, updated_config: dict, plan_survives: bool
    ) -> None:
        plan = {"version": 1, "plan": {}}
        subscription = self._create_subscription(
            prompt="Summarize signups",
            delivery_config=initial_config,
            ai_query_plan=plan,
        )

        deferred_subscription = Subscription.objects.defer("delivery_config").get(id=subscription.id)
        deferred_subscription.delivery_config = updated_config
        deferred_subscription.save(update_fields=["delivery_config"])

        subscription.refresh_from_db()
        assert subscription.ai_query_plan == (plan if plan_survives else None)

    @time_machine.travel("2022-01-11 09:55:00", tick=False)
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

    @time_machine.travel("2022-01-11 09:55:00", tick=False)
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

        with time_machine.travel(datetime(2022, 1, 1) + timedelta(days=UNSUBSCRIBE_TOKEN_EXP_DAYS + 1), tick=False):
            with pytest.raises(jwt.exceptions.ExpiredSignatureError):
                unsubscribe_using_token(token)

        with time_machine.travel(datetime(2022, 1, 1) + timedelta(days=UNSUBSCRIBE_TOKEN_EXP_DAYS - 1), tick=False):
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
                "sent every week on Wednesday",
            ),
            (
                "weekly_wednesday_no_bysetpos",
                {"interval": 1, "frequency": "weekly", "byweekday": ["wednesday"]},
                "sent every week on Wednesday",
            ),
            (
                "daily_weekdays",
                {
                    "interval": 1,
                    "frequency": "daily",
                    "byweekday": ["monday", "tuesday", "wednesday", "thursday", "friday"],
                },
                "sent every day on weekdays",
            ),
            (
                "weekly_multiple_days",
                {"interval": 1, "frequency": "weekly", "byweekday": ["monday", "wednesday", "friday"]},
                "sent every week on Monday, Wednesday and Friday",
            ),
            (
                "weekly_all_days",
                {
                    "interval": 1,
                    "frequency": "weekly",
                    "byweekday": [
                        "monday",
                        "tuesday",
                        "wednesday",
                        "thursday",
                        "friday",
                        "saturday",
                        "sunday",
                    ],
                },
                "sent every week on Monday, Tuesday, Wednesday, Thursday, Friday, Saturday and Sunday",
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
            ("no_bysetpos", None, "sent every month on weekdays"),
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

    @parameterized.expand(
        [
            ("daily", "daily", 1),
            ("weekly", "weekly", 7),
            ("monthly", "monthly", 30),
            ("yearly", "yearly", 365),
            ("unknown_falls_back_to_weekly", "", 7),
        ]
    )
    def test_ai_report_window_days(self, _name, frequency, expected_days):
        # Construct with a valid cadence (the model eagerly builds an rrule on init), then assign
        # the case under test — `ai_report_window_days` reads `frequency` live.
        subscription = Subscription(frequency="daily")
        subscription.frequency = frequency
        assert subscription.ai_report_window_days == expected_days

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
        with time_machine.travel(freeze_date, tick=False):
            subscription = self._create_insight_subscription(
                interval=1,
                frequency="monthly",
                byweekday=["monday", "tuesday", "wednesday", "thursday", "friday"],
                bysetpos=bysetpos,
                start_date=datetime(2021, 1, 1, 9, 0, tzinfo=ZoneInfo("UTC")),
            )
            subscription.set_next_delivery_date()
            assert subscription.next_delivery_date == expected_next


class TestSubscriptionLimit(BaseTest):
    def _create_subscriptions(self, count: int) -> None:
        insight = Insight.objects.create(team=self.team)
        for i in range(count):
            Subscription.objects.create(
                team=self.team,
                insight=insight,
                target_type="email",
                target_value=f"user{i}@posthog.com",
                frequency="daily",
                start_date=datetime(2022, 1, 1, 0, 0, 0, tzinfo=ZoneInfo("UTC")),
            )

    @parameterized.expand(
        [
            ("zero", 0, False),
            ("below_limit", SUBSCRIPTION_COUNT_ALLOWED_ON_FREE_TIER - 1, False),
            ("at_limit", SUBSCRIPTION_COUNT_ALLOWED_ON_FREE_TIER, True),
            ("over_limit", SUBSCRIPTION_COUNT_ALLOWED_ON_FREE_TIER + 1, True),
        ]
    )
    def test_free_org_limit(self, _name: str, count: int, blocked: bool) -> None:
        self.organization.available_product_features = []
        self.organization.save()
        self._create_subscriptions(count)
        result = Subscription.check_subscription_limit(self.team.id, self.organization)
        if blocked:
            assert result is not None
            assert str(SUBSCRIPTION_COUNT_ALLOWED_ON_FREE_TIER) in result
        else:
            assert result is None

    def test_free_org_limit_reads_constant(self) -> None:
        self.organization.available_product_features = []
        self.organization.save()
        self._create_subscriptions(2)
        with patch("products.exports.backend.models.subscription.SUBSCRIPTION_COUNT_ALLOWED_ON_FREE_TIER", 2):
            result = Subscription.check_subscription_limit(self.team.id, self.organization)
        assert result is not None
        assert "2" in result

    def test_paid_org_unlimited_returns_none(self) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.SUBSCRIPTIONS, "name": "subscriptions", "limit": None}
        ]
        self.organization.save()
        self._create_subscriptions(50)
        assert Subscription.check_subscription_limit(self.team.id, self.organization) is None

    @parameterized.expand(
        [
            ("under_limit", 3, 2, None),
            ("at_limit", 3, 3, "3"),
            ("over_limit", 3, 4, "3"),
            ("zero_allowance", 0, 0, "0"),
        ]
    )
    def test_paid_org_numeric_limit(self, _name: str, limit: int, count: int, expected_in_msg: str | None) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.SUBSCRIPTIONS, "name": "subscriptions", "limit": limit}
        ]
        self.organization.save()
        self._create_subscriptions(count)
        result = Subscription.check_subscription_limit(self.team.id, self.organization)
        if expected_in_msg is None:
            assert result is None
        else:
            assert result is not None
            assert expected_in_msg in result

    def test_soft_deleted_excluded_from_count(self) -> None:
        self.organization.available_product_features = []
        self.organization.save()
        self._create_subscriptions(5)
        assert Subscription.check_subscription_limit(self.team.id, self.organization) is not None
        Subscription.objects.filter(team=self.team).update(deleted=True)
        assert Subscription.check_subscription_limit(self.team.id, self.organization) is None
