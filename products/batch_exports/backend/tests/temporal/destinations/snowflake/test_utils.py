import datetime as dt

import pytest

from products.batch_exports.backend.temporal.destinations.snowflake_batch_export import _get_snowflake_query_timeout


@pytest.mark.parametrize(
    "data_interval_start, data_interval_end, expected_timeout",
    [
        # when no data interval start is provided, we use the max timeout of 6 hours
        (None, dt.datetime(2025, 1, 1, 12, 0, 0), 6 * 60 * 60),
        # when the interval is 1 day we use the max timeout of 6 hours
        (dt.datetime(2025, 1, 1, 0, 0, 0), dt.datetime(2025, 1, 2, 0, 0, 0), 6 * 60 * 60),
        # when the interval is 1 hour we expect the timeout to be 48 minutes (as we multiply the interval by 0.8)
        (dt.datetime(2025, 1, 1, 12, 0, 0), dt.datetime(2025, 1, 1, 13, 0, 0), 48 * 60),
        # when interval is 5 minutes, we expect the timeout to be the minimum timeout of 20 minutes
        (dt.datetime(2025, 1, 1, 12, 0, 0), dt.datetime(2025, 1, 1, 12, 5, 0), 20 * 60),
    ],
)
def test_get_snowflake_query_timeout(data_interval_start, data_interval_end, expected_timeout):
    assert _get_snowflake_query_timeout(data_interval_start, data_interval_end) == expected_timeout
