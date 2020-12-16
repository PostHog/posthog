import json
from typing import Any, Callable, Optional

from dateutil.relativedelta import relativedelta
from django.db.models import Q
from freezegun.api import freeze_time

from posthog.models.filters.retention_filter import RetentionFilter
from posthog.test.base import BaseTest


class TestFilter(BaseTest):
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
            },
        )

        with freeze_time("2020-10-01T12:00:00Z"):
            filter = RetentionFilter(data={"date_to": "2020-08-01"})
        self.assertEqual(filter.date_from.isoformat(), "2020-07-22T00:00:00+00:00")
        self.assertEqual(filter.date_to.isoformat(), "2020-08-02T00:00:00+00:00")
        #  Make sure these dates aren't present in final filter to ensure rolling retention
        self.assertEqual(
            filter.to_dict(),
            {
                "date_to": "2020-08-02T00:00:00+00:00",
                "display": "RetentionTable",
                "insight": "RETENTION",
                "period": "Day",
                "retention_type": "retention_recurring",
                "total_intervals": 11,
            },
        )
