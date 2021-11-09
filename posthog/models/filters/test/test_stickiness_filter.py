from posthog.models.event import Event
from posthog.models.filters.stickiness_filter import StickinessFilter
from posthog.test.base import BaseTest


class TestStickinessFilter(BaseTest):
    def test_filter_properties(self):
        earliest_timestamp_func = lambda team_id: Event.objects.earliest_timestamp(team_id)
        filter = StickinessFilter(
            data={
                "interval": "month",
                "date_from": "2020-01-01T20:00:00Z",
                "date_to": "2020-02-01T20:00:00Z",
                "events": [{"id": "$pageview", "custom_name": "Custom event"}],
                "compare": True,
            },
            team=self.team,
            get_earliest_timestamp=earliest_timestamp_func,
        )
        self.assertEqual(
            filter.to_dict(),
            {
                "compare": True,
                "date_from": "2020-01-01T20:00:00Z",
                "date_to": "2020-02-01T20:00:00Z",
                "events": [
                    {
                        "id": "$pageview",
                        "type": "events",
                        "order": None,
                        "name": "$pageview",
                        "custom_name": "Custom event",
                        "math": None,
                        "math_property": None,
                        "math_group_type_index": None,
                        "properties": [],
                    }
                ],
                "insight": "TRENDS",
                "interval": "month",
            },
        )
