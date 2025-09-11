from freezegun.api import freeze_time
from posthog.test.base import BaseTest

from posthog.models.filters.retention_filter import RetentionFilter


class TestFilter(BaseTest):
    maxDiff = None

    def test_fill_date_from_and_date_to(self):
        with freeze_time("2020-10-01T12:00:00Z"):
            filter = RetentionFilter(data={}, team=self.team)
            self.assertEqual(filter.date_from.isoformat(), "2020-09-21T00:00:00+00:00")
            self.assertEqual(filter.date_to.isoformat(), "2020-10-02T00:00:00+00:00")
        #  Make sure these dates aren't present in final filter to ensure rolling retention
        assert filter.to_dict() == {
            "display": "ActionsTable",
            "date_from": "-7d",
            "insight": "RETENTION",
            "period": "Day",
            "retention_type": "retention_recurring",
            "total_intervals": 11,
            "returning_entity": {
                "distinct_id_field": None,
                "id": "$pageview",
                "id_field": None,
                "math": None,
                "math_hogql": None,
                "math_property": None,
                "math_property_revenue_currency": None,
                "math_group_type_index": None,
                "name": "$pageview",
                "custom_name": None,
                "order": None,
                "properties": {},
                "table_name": None,
                "timestamp_field": None,
                "type": "events",
            },
            "target_entity": {
                "distinct_id_field": None,
                "id": "$pageview",
                "id_field": None,
                "math": None,
                "math_hogql": None,
                "math_property": None,
                "math_property_revenue_currency": None,
                "math_group_type_index": None,
                "name": "$pageview",
                "custom_name": None,
                "order": None,
                "properties": {},
                "table_name": None,
                "timestamp_field": None,
                "type": "events",
            },
            "breakdown_attribution_type": "first_touch",
            "breakdown_normalize_url": False,
            "sampling_factor": "",
        }

        with freeze_time("2020-10-01T12:00:00Z"):
            filter = RetentionFilter(data={"date_to": "2020-08-01"}, team=self.team)
        self.assertEqual(filter.date_from.isoformat(), "2020-07-22T00:00:00+00:00")
        self.assertEqual(filter.date_to.isoformat(), "2020-08-02T00:00:00+00:00")
        #  Make sure these dates aren't present in final filter to ensure rolling retention

        # The date_to below is the base value that's provided when the object was created (_date_to).
        # It doesn't match the date_to above because the retention filter will transform date_to to include one period ahead
        assert filter.to_dict() == {
            "date_to": "2020-08-01",
            "display": "ActionsTable",
            "insight": "RETENTION",
            "period": "Day",
            "retention_type": "retention_recurring",
            "total_intervals": 11,
            "returning_entity": {
                "distinct_id_field": None,
                "id": "$pageview",
                "id_field": None,
                "math": None,
                "math_hogql": None,
                "math_property": None,
                "math_property_revenue_currency": None,
                "math_group_type_index": None,
                "name": "$pageview",
                "custom_name": None,
                "order": None,
                "properties": {},
                "table_name": None,
                "timestamp_field": None,
                "type": "events",
            },
            "target_entity": {
                "distinct_id_field": None,
                "id": "$pageview",
                "id_field": None,
                "math": None,
                "math_hogql": None,
                "math_property": None,
                "math_property_revenue_currency": None,
                "math_group_type_index": None,
                "name": "$pageview",
                "custom_name": None,
                "order": None,
                "properties": {},
                "table_name": None,
                "timestamp_field": None,
                "type": "events",
            },
            "breakdown_attribution_type": "first_touch",
            "date_from": "-7d",
            "breakdown_normalize_url": False,
            "sampling_factor": "",
        }

    def test_entities(self):
        filter = RetentionFilter(
            data={
                "target_entity": {"id": "$autocapture", "type": "events"},
                "returning_entity": '{"id": "signup", "type": "events"}',
            }
        ).to_dict()
        self.assertEqual(filter["target_entity"]["id"], "$autocapture")
        self.assertEqual(filter["returning_entity"]["id"], "signup")
