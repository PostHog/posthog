from posthog.test.base import BaseTest

from posthog.models.filters.mixins.funnel import FunnelWindowDaysMixin


class TestFilterMixins(BaseTest):
    def test_funnel_window_days_to_microseconds(self):
        one_day = FunnelWindowDaysMixin.microseconds_from_days(1)
        two_days = FunnelWindowDaysMixin.microseconds_from_days(2)
        three_days = FunnelWindowDaysMixin.microseconds_from_days(3)

        assert 86400000000 == one_day
        assert 172800000000 == two_days
        assert 259200000000 == three_days

    def test_funnel_window_days_to_milliseconds(self):
        one_day = FunnelWindowDaysMixin.milliseconds_from_days(1)
        assert one_day == 86400000
