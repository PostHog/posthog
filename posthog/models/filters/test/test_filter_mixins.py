from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.constants import TRENDS_FUNNEL, TRENDS_LINEAR
from posthog.models.filters.filter import Filter
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

    @parameterized.expand(
        [
            ("known_kind", {"insight": "FUNNELS"}, TRENDS_FUNNEL),
            ("unknown_kind", {"insight": "history"}, TRENDS_LINEAR),
            ("explicit_display_wins", {"insight": "history", "display": TRENDS_FUNNEL}, TRENDS_FUNNEL),
        ]
    )
    def test_display_falls_back_for_an_unknown_insight_kind(
        self, _name: str, data: dict[str, str], expected_display: str
    ) -> None:
        assert Filter(data=data).display == expected_display
