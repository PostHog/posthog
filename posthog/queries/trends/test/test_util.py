from datetime import date, datetime, timezone
from typing import Dict, Optional

import pytest
from freezegun.api import freeze_time

from posthog.constants import TRENDS_CUMULATIVE, TRENDS_PIE
from posthog.models import Cohort, Person
from posthog.models.filters.filter import Filter
from posthog.queries.trends.trends import Trends
from posthog.queries.trends.util import get_next_interval_date_to
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, snapshot_clickhouse_queries

filter_dict = {
    "events": [{"id": "$pageview"}],
    "properties": [{"key": "$browser", "value": "Mac OS X"}],
}


@pytest.mark.parametrize(
    "date_from,interval,expected",
    [
        (datetime(2022, 1, 1, 0, 0, 0), "hour", datetime(2022, 1, 1, 0, 59, 59)),
        (datetime(2022, 1, 1, 0, 0, 0), "day", datetime(2022, 1, 1, 23, 59, 59)),
        (datetime(2022, 1, 1, 0, 0, 0), "week", datetime(2022, 1, 7, 23, 59, 59)),
        (datetime(2022, 1, 1, 0, 0, 0), "month", datetime(2022, 1, 31, 23, 59, 59)),
    ],
)
def test_get_next_interval_date_to(date_from, interval, expected):
    assert get_next_interval_date_to(date_from, Filter(data=dict(date_from=date_from, interval=interval))) == expected
