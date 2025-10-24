import datetime as dt

import pytest

from products.batch_exports.backend.temporal.destinations.snowflake_batch_export import (
    SnowflakeQueryTimeoutError,
    _get_snowflake_query_timeout,
)


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


@pytest.mark.parametrize(
    "query_status, expected_guidance",
    [
        (
            "QUEUED",
            "Warehouse is overloaded with queued queries. Consider scaling up warehouse or reducing concurrent queries.",
        ),
        (
            "RESUMING_WAREHOUSE",
            "Warehouse is resuming from suspended state. Consider keeping warehouse running or using larger warehouse.",
        ),
        (
            "QUEUED_REPARING_WAREHOUSE",
            "Warehouse is repairing. Retry later or contact Snowflake support.",
        ),
        (
            "BLOCKED",
            "Query is blocked. Check for locks or resource contention.",
        ),
        (
            "RUNNING",
            "Query is still running but exceeded timeout. Consider using a larger warehouse or reducing the number of concurrent queries.",
        ),
        (
            "UNKNOWN_STATUS",
            "Query status: UNKNOWN_STATUS",
        ),
    ],
)
def test_snowflake_query_timeout_error_message(query_status, expected_guidance):
    """Test that SnowflakeQueryTimeoutError provides helpful context based on query status."""
    error = SnowflakeQueryTimeoutError(
        operation="COPY INTO",
        timeout=1800.0,
        query_id="abc123",
        query_status=query_status,
    )

    error_message = str(error)
    assert "COPY INTO operation timed out after 1800 seconds" in error_message
    assert "query_id: abc123" in error_message
    assert expected_guidance in error_message
