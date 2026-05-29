import datetime as dt

from parameterized import parameterized

from posthog.models.pulse import PulseSubscriptionFrequency
from posthog.temporal.ai.pulse.period import period_bounds, period_key


class TestPeriodKey:
    @parameterized.expand(
        [
            # 2026-05-29 is a Friday in ISO week 22 of 2026
            ("weekly", PulseSubscriptionFrequency.WEEKLY, dt.datetime(2026, 5, 29, 14, 3, tzinfo=dt.UTC), "2026-W22"),
            ("daily", PulseSubscriptionFrequency.DAILY, dt.datetime(2026, 5, 29, 14, 3, tzinfo=dt.UTC), "2026-05-29"),
        ]
    )
    def test_period_key(self, _name, frequency, now, expected):
        assert period_key(now, frequency) == expected

    def test_weekly_key_is_stable_within_week(self):
        mon = dt.datetime(2026, 5, 25, 0, 0, tzinfo=dt.UTC)
        sun = dt.datetime(2026, 5, 31, 23, 59, tzinfo=dt.UTC)
        assert period_key(mon, PulseSubscriptionFrequency.WEEKLY) == period_key(sun, PulseSubscriptionFrequency.WEEKLY)

    def test_weekly_bounds_span_seven_days(self):
        now = dt.datetime(2026, 5, 29, 14, 3, tzinfo=dt.UTC)
        start, end = period_bounds(now, PulseSubscriptionFrequency.WEEKLY)
        assert (end - start) == dt.timedelta(days=7)
        assert end == now

    def test_daily_bounds_span_one_day(self):
        now = dt.datetime(2026, 5, 29, 14, 3, tzinfo=dt.UTC)
        start, end = period_bounds(now, PulseSubscriptionFrequency.DAILY)
        assert (end - start) == dt.timedelta(days=1)
