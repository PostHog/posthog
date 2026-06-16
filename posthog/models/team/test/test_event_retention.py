from parameterized import parameterized

from posthog.models.team.event_retention import parse_events_feature_to_period


class TestParseEventsFeatureToPeriod:
    @parameterized.expand(
        [
            (None, "7y"),
            ({"limit": 12, "unit": "months"}, "1y"),
            ({"limit": 24, "unit": "months"}, "2y"),
            ({"limit": 60, "unit": "months"}, "5y"),
            ({"limit": 84, "unit": "months"}, "7y"),
            ({"limit": 1, "unit": "year"}, "1y"),
            ({"limit": 2, "unit": "years"}, "2y"),
            ({"limit": 3, "unit": "years"}, "3y"),
            ({"limit": 36, "unit": "months"}, "3y"),
            ({"limit": 5, "unit": "years"}, "5y"),
            ({"limit": 7, "unit": "years"}, "7y"),
            ({"limit": 10, "unit": "years"}, "7y"),
            ({"limit": 365, "unit": "days"}, "1y"),
            ({"limit": None, "unit": "years"}, "7y"),
            ({"limit": 1, "unit": "decades"}, "7y"),
            ({"limit": 0, "unit": "years"}, "7y"),
            ({"limit": 0, "unit": "months"}, "7y"),
            ({"limit": 11, "unit": "months"}, "7y"),
            ({"limit": -5, "unit": "years"}, "7y"),
        ]
    )
    def test_parse(self, feature: dict | None, expected: str) -> None:
        assert parse_events_feature_to_period(feature) == expected
