"""Tests for the day-boundary ack rule.

The single invariant the replace design hangs on: we only ever ack at UTC day
boundaries, never mid-day. Duckgres watermarks are bucket-START labels and ack
deletes `bucket_start <= watermark`, so:

- acking exact midnight would delete the new day's first bucket (money loss);
- acking mid-day would make the next pull serve a partial-day remainder, which
  the replace-upsert would then use to overwrite the full day (money loss).

The safe ack for "everything through day D is ours" is `midnight(D+1) - 1s`:
it covers every bucket label of day D (the last one is `midnight(D+1) - width`
for any width >= 1s) and no label of day D+1. We always ack through the end of
the day BEFORE watermark_high's date — conservative (the high's own day is
picked up on the first pull after the next midnight), never wrong, and needs
no knowledge of duckgres's bucket width.
"""

import datetime as dt

from posthog.temporal.duckgres_usage.acking import day_boundary_ack

EPOCH = dt.datetime(1, 1, 1, tzinfo=dt.UTC)


def test_mid_day_high_acks_end_of_previous_day() -> None:
    ack = day_boundary_ack(
        watermark_low=dt.datetime(2026, 7, 5, 23, 59, 59, tzinfo=dt.UTC),
        watermark_high=dt.datetime(2026, 7, 7, 12, 39, tzinfo=dt.UTC),
    )
    assert ack == dt.datetime(2026, 7, 6, 23, 59, 59, tzinfo=dt.UTC)


def test_nothing_to_ack_when_high_is_in_the_day_after_low() -> None:
    # Steady state: low is yesterday's end, high is mid-today — today is open.
    ack = day_boundary_ack(
        watermark_low=dt.datetime(2026, 7, 6, 23, 59, 59, tzinfo=dt.UTC),
        watermark_high=dt.datetime(2026, 7, 7, 12, 39, tzinfo=dt.UTC),
    )
    assert ack is None


def test_high_at_exact_midnight_label_does_not_ack_the_new_day() -> None:
    # watermark_high == 00:00:00 of day D is day D's FIRST bucket label — day D
    # is open, nothing new closed.
    ack = day_boundary_ack(
        watermark_low=dt.datetime(2026, 7, 6, 23, 59, 59, tzinfo=dt.UTC),
        watermark_high=dt.datetime(2026, 7, 7, 0, 0, 0, tzinfo=dt.UTC),
    )
    assert ack is None


def test_high_at_last_bucket_of_day_is_conservative() -> None:
    # high == 23:59:00 of day 7 means day 7 is actually complete, but we can't
    # know that without knowing the bucket width — so we wait for the first
    # pull after midnight (high jumps to day 8's labels) to ack day 7.
    ack = day_boundary_ack(
        watermark_low=dt.datetime(2026, 7, 6, 23, 59, 59, tzinfo=dt.UTC),
        watermark_high=dt.datetime(2026, 7, 7, 23, 59, 0, tzinfo=dt.UTC),
    )
    assert ack is None


def test_empty_window_never_acks() -> None:
    low = high = dt.datetime(2026, 7, 6, 23, 59, 59, tzinfo=dt.UTC)
    assert day_boundary_ack(watermark_low=low, watermark_high=high) is None


def test_never_acked_cursor_acks_everything_through_yesterday() -> None:
    ack = day_boundary_ack(
        watermark_low=EPOCH,
        watermark_high=dt.datetime(2026, 7, 7, 12, 39, tzinfo=dt.UTC),
    )
    assert ack == dt.datetime(2026, 7, 6, 23, 59, 59, tzinfo=dt.UTC)


def test_multi_day_catchup_acks_through_end_of_last_complete_day() -> None:
    ack = day_boundary_ack(
        watermark_low=dt.datetime(2026, 7, 3, 23, 59, 59, tzinfo=dt.UTC),
        watermark_high=dt.datetime(2026, 7, 7, 9, 0, tzinfo=dt.UTC),
    )
    assert ack == dt.datetime(2026, 7, 6, 23, 59, 59, tzinfo=dt.UTC)


def test_ack_is_always_strictly_before_the_open_day() -> None:
    ack = day_boundary_ack(
        watermark_low=EPOCH,
        watermark_high=dt.datetime(2026, 7, 7, 0, 1, 0, tzinfo=dt.UTC),
    )
    assert ack is not None
    assert ack < dt.datetime(2026, 7, 7, 0, 0, 0, tzinfo=dt.UTC)
    assert ack.tzinfo is dt.UTC
