from typing import cast

from parameterized import parameterized

from posthog.models.organization import ProductFeature
from posthog.models.team.event_retention import parse_events_feature_to_months


class TestParseEventsFeatureToMonths:
    @parameterized.expand(
        [
            (None, 84),
            ({"limit": 1, "unit": "year"}, 12),
            ({"limit": 2, "unit": "years"}, 24),
            ({"limit": 5, "unit": "years"}, 60),
            ({"limit": 7, "unit": "years"}, 84),
            ({"limit": 10, "unit": "years"}, 120),
            ({"limit": 6, "unit": "months"}, 6),
            ({"limit": 18, "unit": "months"}, 18),
            ({"limit": 84, "unit": "months"}, 84),
            ({"limit": None, "unit": "years"}, 84),
            ({"limit": 1, "unit": "decades"}, 84),
            ({"limit": 90, "unit": "days"}, 84),
            ({"limit": 0, "unit": "years"}, 84),
            ({"limit": 0, "unit": "months"}, 84),
            ({"limit": -5, "unit": "years"}, 84),
        ]
    )
    def test_parse(self, feature: dict | None, expected: int) -> None:
        assert parse_events_feature_to_months(cast(ProductFeature | None, feature)) == expected
