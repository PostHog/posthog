import datetime as dt

import pytest

from posthog.batch_exports.models import BatchExport

from products.batch_exports.backend.temporal.backfill_batch_export import _align_timestamp_to_interval


@pytest.mark.parametrize(
    "timestamp,interval,interval_offset,timezone,expected",
    [
        # Hourly interval — 10:37 aligns to 10:00
        (
            dt.datetime(2021, 1, 15, 10, 37, 45, tzinfo=dt.UTC),
            "hour",
            None,
            "UTC",
            dt.datetime(2021, 1, 15, 10, 0, 0, tzinfo=dt.UTC),
        ),
        # 5-minute interval — 10:37 aligns to 10:35
        (
            dt.datetime(2021, 1, 15, 10, 37, 45, tzinfo=dt.UTC),
            "every 5 minutes",
            None,
            "UTC",
            dt.datetime(2021, 1, 15, 10, 35, 0, tzinfo=dt.UTC),
        ),
        # Daily with offset_hour=5 — 10:30 aligns to 5am same day
        (
            dt.datetime(2021, 1, 15, 10, 30, 0, tzinfo=dt.UTC),
            "day",
            5 * 3600,
            "UTC",
            dt.datetime(2021, 1, 15, 5, 0, 0, tzinfo=dt.UTC),
        ),
        # Daily with offset_hour=5 — 4:30am aligns to 5am previous day
        (
            dt.datetime(2021, 1, 15, 4, 30, 0, tzinfo=dt.UTC),
            "day",
            5 * 3600,
            "UTC",
            dt.datetime(2021, 1, 14, 5, 0, 0, tzinfo=dt.UTC),
        ),
        # Weekly starting Monday at 5am — Thursday 10am aligns to Monday 5am
        (
            dt.datetime(2021, 1, 14, 10, 0, 0, tzinfo=dt.UTC),
            "week",
            1 * 86400 + 5 * 3600,
            "UTC",
            dt.datetime(2021, 1, 11, 5, 0, 0, tzinfo=dt.UTC),
        ),
        # Daily at 1am US/Pacific — 10:00 UTC (2am PST) aligns to 9:00 UTC (1am PST)
        (
            dt.datetime(2021, 1, 15, 10, 0, 0, tzinfo=dt.UTC),
            "day",
            1 * 3600,
            "US/Pacific",
            dt.datetime(2021, 1, 15, 9, 0, 0, tzinfo=dt.UTC),
        ),
        # Daily at 1am US/Pacific — 8:30 UTC (0:30am PST) aligns to previous day's 1am PST
        (
            dt.datetime(2021, 1, 15, 8, 30, 0, tzinfo=dt.UTC),
            "day",
            1 * 3600,
            "US/Pacific",
            dt.datetime(2021, 1, 14, 9, 0, 0, tzinfo=dt.UTC),
        ),
    ],
)
def test_align_timestamp_to_interval(timestamp, interval, interval_offset, timezone, expected):
    batch_export = BatchExport(interval=interval, interval_offset=interval_offset, timezone=timezone)
    assert _align_timestamp_to_interval(timestamp, batch_export) == expected
