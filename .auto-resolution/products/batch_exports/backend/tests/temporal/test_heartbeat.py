import datetime as dt

import pytest

from products.batch_exports.backend.temporal.heartbeat import BatchExportRangeHeartbeatDetails


@pytest.mark.parametrize(
    "initial_done_ranges,done_range,expected_index",
    [
        # Case 1: Inserting into an empty initial list.
        ([], (dt.datetime.fromtimestamp(5), dt.datetime.fromtimestamp(6)), 0),
        # Case 2: Inserting into middle of initial list.
        (
            [
                (dt.datetime.fromtimestamp(0), dt.datetime.fromtimestamp(5)),
                (dt.datetime.fromtimestamp(6), dt.datetime.fromtimestamp(10)),
            ],
            (dt.datetime.fromtimestamp(5), dt.datetime.fromtimestamp(6)),
            1,
        ),
        # Case 3: Inserting into beginning of initial list.
        (
            [
                (dt.datetime.fromtimestamp(1), dt.datetime.fromtimestamp(5)),
                (dt.datetime.fromtimestamp(6), dt.datetime.fromtimestamp(10)),
            ],
            (dt.datetime.fromtimestamp(0), dt.datetime.fromtimestamp(1)),
            0,
        ),
        # Case 4: Inserting into end of initial list.
        (
            [(dt.datetime.fromtimestamp(0), dt.datetime.fromtimestamp(10))],
            (dt.datetime.fromtimestamp(10), dt.datetime.fromtimestamp(11)),
            1,
        ),
        # Case 5: Inserting disconnected range into middle of initial list.
        (
            [
                (dt.datetime.fromtimestamp(0), dt.datetime.fromtimestamp(10)),
                (dt.datetime.fromtimestamp(15), dt.datetime.fromtimestamp(20)),
            ],
            (dt.datetime.fromtimestamp(12), dt.datetime.fromtimestamp(13)),
            1,
        ),
    ],
)
def test_insert_done_range(initial_done_ranges, done_range, expected_index):
    """Test `BatchExportRangeHeartbeatDetails` inserts a done range in the expected index.

    We avoid merging ranges to maintain the original index so we can assert it matches
    the expected index.
    """
    heartbeat_details = BatchExportRangeHeartbeatDetails()
    heartbeat_details.done_ranges.extend(initial_done_ranges)
    heartbeat_details.insert_done_range(done_range, merge=False)

    assert len(heartbeat_details.done_ranges) == len(initial_done_ranges) + 1
    assert heartbeat_details.done_ranges.index(done_range) == expected_index


@pytest.mark.parametrize(
    "initial_done_ranges,expected_done_ranges",
    [
        # Case 1: Disconnected ranges are not merged.
        (
            [
                (dt.datetime.fromtimestamp(0), dt.datetime.fromtimestamp(5)),
                (dt.datetime.fromtimestamp(6), dt.datetime.fromtimestamp(10)),
            ],
            [
                (dt.datetime.fromtimestamp(0), dt.datetime.fromtimestamp(5)),
                (dt.datetime.fromtimestamp(6), dt.datetime.fromtimestamp(10)),
            ],
        ),
        # Case 2: Connected ranges are merged.
        (
            [
                (dt.datetime.fromtimestamp(0), dt.datetime.fromtimestamp(5)),
                (dt.datetime.fromtimestamp(5), dt.datetime.fromtimestamp(10)),
            ],
            [(dt.datetime.fromtimestamp(0), dt.datetime.fromtimestamp(10))],
        ),
        # Case 3: Connected ranges are merged, but disconnected are not.
        (
            [
                (dt.datetime.fromtimestamp(0), dt.datetime.fromtimestamp(5)),
                (dt.datetime.fromtimestamp(5), dt.datetime.fromtimestamp(10)),
                (dt.datetime.fromtimestamp(11), dt.datetime.fromtimestamp(12)),
            ],
            [
                (dt.datetime.fromtimestamp(0), dt.datetime.fromtimestamp(10)),
                (dt.datetime.fromtimestamp(11), dt.datetime.fromtimestamp(12)),
            ],
        ),
    ],
)
def test_merge_done_ranges(initial_done_ranges, expected_done_ranges):
    """Test `BatchExportRangeHeartbeatDetails` merges done ranges."""
    heartbeat_details = BatchExportRangeHeartbeatDetails()
    heartbeat_details.done_ranges.extend(initial_done_ranges)
    heartbeat_details.merge_done_ranges()

    assert heartbeat_details.done_ranges == expected_done_ranges
