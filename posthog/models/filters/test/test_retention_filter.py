import json
from typing import Any, Callable, Optional

from dateutil.relativedelta import relativedelta
from django.db.models import Q
from freezegun.api import freeze_time

from posthog.constants import TREND_FILTER_TYPE_EVENTS
from posthog.models.filters.retention_filter import RetentionFilter
from posthog.test.base import BaseTest


class TestFilter(BaseTest):
    maxDiff = None

    def test_fill_date_from_and_date_to(self):
        with freeze_time("2020-10-01T12:00:00Z"):
            filter = RetentionFilter(data={})
            self.assertEqual(filter.date_from.isoformat(), "2020-09-21T00:00:00+00:00")
            self.assertEqual(filter.date_to.isoformat(), "2020-10-02T00:00:00+00:00")
        #  Make sure these dates aren't present in final filter to ensure rolling retention
        self.assertEqual(
            filter.to_dict(),
            {
                "display": "RetentionTable",
                "insight": "RETENTION",
                "period": "Day",
                "retention_type": "retention_recurring",
                "total_intervals": 11,
                "returning_entity": {
                    "id": "$pageview",
                    "math": None,
                    "math_property": None,
                    "name": "$pageview",
                    "custom_name": None,
                    "order": None,
                    "properties": [],
                    "type": "events",
                },
                "target_entity": {
                    "id": "$pageview",
                    "math": None,
                    "math_property": None,
                    "name": "$pageview",
                    "custom_name": None,
                    "order": None,
                    "properties": [],
                    "type": "events",
                },
            },
        )

        with freeze_time("2020-10-01T12:00:00Z"):
            filter = RetentionFilter(data={"date_to": "2020-08-01"})
        self.assertEqual(filter.date_from.isoformat(), "2020-07-22T00:00:00+00:00")
        self.assertEqual(filter.date_to.isoformat(), "2020-08-02T00:00:00+00:00")
        #  Make sure these dates aren't present in final filter to ensure rolling retention

        # The date_to below is the base value that's provided when the object was created (_date_to).
        # It doesn't match the date_to above because the retention filter will transform date_to to include one period ahead
        self.assertEqual(
            filter.to_dict(),
            {
                "date_to": "2020-08-01",
                "display": "RetentionTable",
                "insight": "RETENTION",
                "period": "Day",
                "retention_type": "retention_recurring",
                "total_intervals": 11,
                "returning_entity": {
                    "id": "$pageview",
                    "math": None,
                    "math_property": None,
                    "name": "$pageview",
                    "custom_name": None,
                    "order": None,
                    "properties": [],
                    "type": "events",
                },
                "target_entity": {
                    "id": "$pageview",
                    "math": None,
                    "math_property": None,
                    "name": "$pageview",
                    "custom_name": None,
                    "order": None,
                    "properties": [],
                    "type": "events",
                },
            },
        )

    def test_entities(self):
        filter = RetentionFilter(
            data={
                "target_entity": {"id": "$autocapture", "type": "events"},
                "returning_entity": '{"id": "signup", "type": "events"}',
            }
        ).to_dict()
        self.assertEqual(filter["target_entity"]["id"], "$autocapture")
        self.assertEqual(filter["returning_entity"]["id"], "signup")
