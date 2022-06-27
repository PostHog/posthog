from posthog.models.filters import PathFilter
from posthog.test.base import BaseTest


class TestPathFilter(BaseTest):
    def test_to_dict(self):
        filter = PathFilter(
            data={
                "date_from": "-14d",
                "exclude_events": [],
                "include_custom_events": ["potato"],
                "filter_test_accounts": False,
                "include_event_types": ["$pageview", "$screen", "custom_event"],
                "insight": "PATHS",
                "start_point": "https://www.random.com/pricing/",
                "step_limit": 3,
            }
        )
        self.assertEqual(
            filter.to_dict(),
            {
                "date_from": "-14d",
                "include_event_types": ["$pageview", "$screen", "custom_event"],
                "insight": "PATHS",
                "start_point": "https://www.random.com/pricing",
                "step_limit": 3,
                "include_custom_events": ["potato"],
                # always included defaults
                "breakdown_attribution_type": "first_touch",
                "interval": "day",
            },
        )
