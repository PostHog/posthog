from posthog.test.base import BaseTest

from posthog.models.filters.mixins.funnel import FunnelWindowDaysMixin


class TestFilterMixins(BaseTest):
    def test_funnel_window_days_to_microseconds(self):
        one_day = FunnelWindowDaysMixin.microseconds_from_days(1)
        two_days = FunnelWindowDaysMixin.microseconds_from_days(2)
        three_days = FunnelWindowDaysMixin.microseconds_from_days(3)

        self.assertEqual(86_400_000_000, one_day)
        self.assertEqual(17_2800_000_000, two_days)
        self.assertEqual(259_200_000_000, three_days)

    def test_funnel_window_days_to_milliseconds(self):
        one_day = FunnelWindowDaysMixin.milliseconds_from_days(1)
        self.assertEqual(one_day, 86_400_000)
