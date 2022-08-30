from datetime import datetime

import pytest

from posthog.models.filters.filter import Filter
from posthog.queries.trends.util import get_next_interval_date_to

filter_dict = {
    "events": [{"id": "$pageview"}],
    "properties": [{"key": "$browser", "value": "Mac OS X"}],
}


@pytest.mark.parametrize(
    "date_from,interval,expected",
    [
        (datetime(2022, 1, 1, 0, 0, 0), "hour", datetime(2022, 1, 1, 1, 0, 0)),
        (datetime(2022, 1, 1, 0, 0, 0), "day", datetime(2022, 1, 2, 0, 0, 0)),
        (datetime(2022, 1, 1, 0, 0, 0), "week", datetime(2022, 1, 8, 0, 0, 0)),
        (datetime(2022, 1, 1, 0, 0, 0), "month", datetime(2022, 2, 1, 0, 0, 0)),
    ],
)
def test_get_next_interval_date_to(date_from, interval, expected):
    assert get_next_interval_date_to(date_from, Filter(data=dict(date_from=date_from, interval=interval))) == expected
