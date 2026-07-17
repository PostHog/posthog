from posthog.test.base import BaseTest

from posthog.models.filters.stickiness_filter import StickinessFilter
from posthog.models.filters.utils import earliest_timestamp_func


class TestStickinessFilter(BaseTest):
    def test_filter_properties(self):
        filter = StickinessFilter(
            data={
                "interval": "month",
                "date_from": "2020-01-01T20:00:00Z",
                "date_to": "2020-02-01T20:00:00Z",
                "events": [{"id": "$pageview", "custom_name": "Custom event"}],
                "compare": True,
                "sampling_factor": 0.1,
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
                        "distinct_id_field": None,
                        "id": "$pageview",
                        "id_field": None,
                        "type": "events",
                        "order": None,
                        "name": "$pageview",
                        "custom_name": "Custom event",
                        "math": None,
                        "math_hogql": None,
                        "math_property": None,
                        "math_property_revenue_currency": None,
                        "math_group_type_index": None,
                        "properties": {},
                        "table_name": None,
                        "timestamp_field": None,
                    }
                ],
                "insight": "STICKINESS",
                "interval": "month",
                "sampling_factor": 0.1,
            },
        )
