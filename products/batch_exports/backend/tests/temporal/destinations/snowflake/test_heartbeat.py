"""
Test the Snowflake Heartbeat Details.

TODO: This can be removed once we migrate to the new workflow which doesn't make use of the heartbeat details.
"""

import datetime as dt

import pytest

from products.batch_exports.backend.temporal.destinations.snowflake_batch_export import SnowflakeHeartbeatDetails


@pytest.mark.parametrize(
    "details",
    [
        ([(dt.datetime.now().isoformat(), dt.datetime.now().isoformat())], 10, 1),
        (
            [(dt.datetime.now().isoformat(), dt.datetime.now().isoformat())],
            10,
        ),
    ],
)
def test_snowflake_heartbeat_details_parses_from_tuple(details):
    class FakeActivity:
        def info(self):
            return FakeInfo()

    class FakeInfo:
        def __init__(self):
            self.heartbeat_details = details

    snowflake_details = SnowflakeHeartbeatDetails.from_activity(FakeActivity())
    expected_done_ranges = details[0]

    assert snowflake_details.done_ranges == [
        (
            dt.datetime.fromisoformat(expected_done_ranges[0][0]),
            dt.datetime.fromisoformat(expected_done_ranges[0][1]),
        )
    ]
