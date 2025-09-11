from posthog.test.base import BaseTest

from posthog.models.filters.lifecycle_filter import LifecycleFilter
from posthog.utils import relative_date_parse


class TestLifecycleFilter(BaseTest):
    def test_filter_properties(self):
        target_date = "2023-05-15"
        lifecycle_type = "new"
        filter = LifecycleFilter(
            data={
                "breakdown_attribution_type": "first_touch",
                "breakdown_normalize_url": "False",
                "date_from": "-14d",
                "display": "ActionsLineGraph",
                "events": '[{"id": "$pageview", "type": "events", "order": 0, "name": "$pageview", "custom_name": null, "math": "total", "math_property": null, "math_group_type_index": null, "properties": {}}]',
                "insight": "LIFECYCLE",
                "interval": "week",
                "sampling_factor": "",
                "shown_as": "Lifecycle",
                "smoothing_intervals": "1",
                "entity_id": "$pageview",
                "entity_type": "events",
                "entity_math": "total",
                "target_date": target_date,
                "entity_order": "0",
                "lifecycle_type": lifecycle_type,
                "cache_invalidation_key": "ZY7tZ2Ak",
                "is_simplified": True,
            },
            team=self.team,
        )

        self.assertEqual(
            filter.to_dict(),
            {
                "breakdown_attribution_type": "first_touch",
                "breakdown_normalize_url": False,
                "date_from": "-14d",
                "display": "ActionsLineGraph",
                "events": [
                    {
                        "distinct_id_field": None,
                        "id": "$pageview",
                        "id_field": None,
                        "type": "events",
                        "order": 0,
                        "name": "$pageview",
                        "custom_name": None,
                        "math": "total",
                        "math_property": None,
                        "math_property_revenue_currency": None,
                        "math_hogql": None,
                        "math_group_type_index": None,
                        "properties": {},
                        "timestamp_field": None,
                        "table_name": None,
                    }
                ],
                "entity_id": "$pageview",
                "entity_math": "total",
                "entity_order": "0",
                "entity_type": "events",
                "insight": "LIFECYCLE",
                "interval": "week",
                "sampling_factor": "",
                "shown_as": "Lifecycle",
                "smoothing_intervals": 1,
            },
        )
        self.assertEqual(filter.lifecycle_type, lifecycle_type)
        self.assertEqual(
            filter.target_date,
            relative_date_parse(target_date, self.team.timezone_info),
        )
