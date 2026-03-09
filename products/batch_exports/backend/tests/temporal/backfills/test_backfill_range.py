import datetime as dt
from zoneinfo import ZoneInfo

import pytest

from products.batch_exports.backend.temporal.backfill_batch_export import backfill_range


@pytest.mark.parametrize(
    "start_at,end_at,step,expected",
    [
        (
            dt.datetime(2023, 1, 1, 0, 0, 0, tzinfo=dt.UTC),
            dt.datetime(2023, 1, 2, 0, 0, 0, tzinfo=dt.UTC),
            dt.timedelta(days=1),
            [
                (
                    dt.datetime(2023, 1, 1, 0, 0, 0, tzinfo=dt.UTC),
                    dt.datetime(2023, 1, 2, 0, 0, 0, tzinfo=dt.UTC),
                )
            ],
        ),
        (
            dt.datetime(2023, 1, 1, 10, 0, 0, tzinfo=dt.UTC),
            dt.datetime(2023, 1, 1, 12, 20, 0, tzinfo=dt.UTC),
            dt.timedelta(hours=1),
            [
                (
                    dt.datetime(2023, 1, 1, 10, 0, 0, tzinfo=dt.UTC),
                    dt.datetime(2023, 1, 1, 11, 0, 0, tzinfo=dt.UTC),
                ),
                (
                    dt.datetime(2023, 1, 1, 11, 0, 0, tzinfo=dt.UTC),
                    dt.datetime(2023, 1, 1, 12, 0, 0, tzinfo=dt.UTC),
                ),
            ],
        ),
        (
            dt.datetime(2023, 1, 1, 0, 0, 0, tzinfo=dt.UTC),
            dt.datetime(2023, 1, 2, 0, 0, 0, tzinfo=dt.UTC),
            dt.timedelta(hours=12),
            [
                (
                    dt.datetime(2023, 1, 1, 0, 0, 0, tzinfo=dt.UTC),
                    dt.datetime(2023, 1, 1, 12, 0, 0, tzinfo=dt.UTC),
                ),
                (
                    dt.datetime(2023, 1, 1, 12, 0, 0, tzinfo=dt.UTC),
                    dt.datetime(2023, 1, 2, 0, 0, 0, tzinfo=dt.UTC),
                ),
            ],
        ),
        (
            dt.datetime(2023, 1, 1, 6, 0, 0, tzinfo=ZoneInfo("US/Pacific")),
            dt.datetime(2023, 1, 5, 6, 0, 0, tzinfo=ZoneInfo("US/Pacific")),
            dt.timedelta(days=1),
            [
                (
                    dt.datetime(2023, 1, 1, 6, 0, 0, tzinfo=ZoneInfo("US/Pacific")),
                    dt.datetime(2023, 1, 2, 6, 0, 0, tzinfo=ZoneInfo("US/Pacific")),
                ),
                (
                    dt.datetime(2023, 1, 2, 6, 0, 0, tzinfo=ZoneInfo("US/Pacific")),
                    dt.datetime(2023, 1, 3, 6, 0, 0, tzinfo=ZoneInfo("US/Pacific")),
                ),
                (
                    dt.datetime(2023, 1, 3, 6, 0, 0, tzinfo=ZoneInfo("US/Pacific")),
                    dt.datetime(2023, 1, 4, 6, 0, 0, tzinfo=ZoneInfo("US/Pacific")),
                ),
                (
                    dt.datetime(2023, 1, 4, 6, 0, 0, tzinfo=ZoneInfo("US/Pacific")),
                    dt.datetime(2023, 1, 5, 6, 0, 0, tzinfo=ZoneInfo("US/Pacific")),
                ),
            ],
        ),
        (
            dt.datetime(2023, 1, 1, 0, 0, 0, tzinfo=dt.UTC),
            None,
            dt.timedelta(days=1),
            [
                (
                    dt.datetime(2023, 1, 1, 0, 0, 0, tzinfo=dt.UTC),
                    dt.datetime(2023, 1, 2, 0, 0, 0, tzinfo=dt.UTC),
                ),
                (
                    dt.datetime(2023, 1, 2, 0, 0, 0, tzinfo=dt.UTC),
                    dt.datetime(2023, 1, 3, 0, 0, 0, tzinfo=dt.UTC),
                ),
                (
                    dt.datetime(2023, 1, 3, 0, 0, 0, tzinfo=dt.UTC),
                    dt.datetime(2023, 1, 4, 0, 0, 0, tzinfo=dt.UTC),
                ),
                (
                    dt.datetime(2023, 1, 4, 0, 0, 0, tzinfo=dt.UTC),
                    dt.datetime(2023, 1, 5, 0, 0, 0, tzinfo=dt.UTC),
                ),
            ],
        ),
        (
            None,
            dt.datetime(2023, 1, 5, 0, 0, 0, tzinfo=dt.UTC),
            dt.timedelta(days=1),
            [
                (
                    None,
                    dt.datetime(2023, 1, 5, 0, 0, 0, tzinfo=dt.UTC),
                ),
            ],
        ),
        (
            dt.datetime(2023, 1, 1, 6, 0, 0, tzinfo=ZoneInfo("Europe/Berlin")),
            dt.datetime(2023, 1, 15, 6, 0, 0, tzinfo=ZoneInfo("Europe/Berlin")),
            dt.timedelta(days=7),
            [
                (
                    dt.datetime(2023, 1, 1, 6, 0, 0, tzinfo=ZoneInfo("Europe/Berlin")),
                    dt.datetime(2023, 1, 8, 6, 0, 0, tzinfo=ZoneInfo("Europe/Berlin")),
                ),
                (
                    dt.datetime(2023, 1, 8, 6, 0, 0, tzinfo=ZoneInfo("Europe/Berlin")),
                    dt.datetime(2023, 1, 15, 6, 0, 0, tzinfo=ZoneInfo("Europe/Berlin")),
                ),
            ],
        ),
    ],
)
def test_backfill_range(start_at, end_at, step, expected):
    """Test the backfill_range function yields expected ranges of dates."""
    generator = backfill_range(start_at, end_at, step)

    if end_at is not None:
        result = list(generator)
    else:
        result = [next(generator) for _ in range(len(expected))]

    assert result == expected


def test_backfill_range_dst_spring_forward():
    """backfill_range with timezone produces DST-aware intervals during spring-forward.

    For a daily batch export at midnight US/Eastern, intervals spanning the 2024
    spring-forward (March 10) should have variable UTC lengths: 24h before,
    23h on the transition day, then 24h after.
    """
    # _align_timestamp_to_interval outputs UTC. A daily export at midnight ET:
    # Mar 9 midnight EST = 05:00 UTC
    start_at = dt.datetime(2024, 3, 9, 5, 0, 0, tzinfo=dt.UTC)
    # Mar 12 midnight EDT = 04:00 UTC (after spring-forward)
    end_at = dt.datetime(2024, 3, 12, 4, 0, 0, tzinfo=dt.UTC)
    step = dt.timedelta(days=1)

    result = list(backfill_range(start_at, end_at, step, timezone="US/Eastern"))

    # Should produce 3 intervals aligned to local midnight:
    # [Mar 9 05:00, Mar 10 05:00) = 24h (pre-DST)
    # [Mar 10 05:00, Mar 11 04:00) = 23h (DST transition day)
    # [Mar 11 04:00, Mar 12 04:00) = 24h (post-DST)
    assert len(result) == 3, f"Expected 3 intervals covering the full range, got {len(result)}"

    assert result[0] == (
        dt.datetime(2024, 3, 9, 5, 0, 0, tzinfo=dt.UTC),
        dt.datetime(2024, 3, 10, 5, 0, 0, tzinfo=dt.UTC),
    )
    assert result[1] == (
        dt.datetime(2024, 3, 10, 5, 0, 0, tzinfo=dt.UTC),
        dt.datetime(2024, 3, 11, 4, 0, 0, tzinfo=dt.UTC),
    )
    assert result[2] == (
        dt.datetime(2024, 3, 11, 4, 0, 0, tzinfo=dt.UTC),
        dt.datetime(2024, 3, 12, 4, 0, 0, tzinfo=dt.UTC),
    )


def test_backfill_range_dst_fall_back():
    """backfill_range with timezone produces DST-aware intervals during fall-back.

    During fall-back (2024-11-03), midnight ET shifts from 04:00 UTC (EDT) to
    05:00 UTC (EST). With timezone awareness, intervals align to local midnight,
    producing a 25h interval on the transition day.
    """
    # Midnight EDT on Nov 2 = 04:00 UTC
    start_at = dt.datetime(2024, 11, 2, 4, 0, 0, tzinfo=dt.UTC)
    # Midnight EST on Nov 5 = 05:00 UTC (after fall-back)
    end_at = dt.datetime(2024, 11, 5, 5, 0, 0, tzinfo=dt.UTC)
    step = dt.timedelta(days=1)

    result = list(backfill_range(start_at, end_at, step, timezone="US/Eastern"))

    # Should produce 3 intervals aligned to local midnight:
    # [Nov 2 04:00, Nov 3 04:00) = 24h (pre-DST)
    # [Nov 3 04:00, Nov 4 05:00) = 25h (DST transition day)
    # [Nov 4 05:00, Nov 5 05:00) = 24h (post-DST)
    assert len(result) == 3

    assert result[0] == (
        dt.datetime(2024, 11, 2, 4, 0, 0, tzinfo=dt.UTC),
        dt.datetime(2024, 11, 3, 4, 0, 0, tzinfo=dt.UTC),
    )
    assert result[1] == (
        dt.datetime(2024, 11, 3, 4, 0, 0, tzinfo=dt.UTC),
        dt.datetime(2024, 11, 4, 5, 0, 0, tzinfo=dt.UTC),
    )
    assert result[2] == (
        dt.datetime(2024, 11, 4, 5, 0, 0, tzinfo=dt.UTC),
        dt.datetime(2024, 11, 5, 5, 0, 0, tzinfo=dt.UTC),
    )
