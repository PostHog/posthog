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
