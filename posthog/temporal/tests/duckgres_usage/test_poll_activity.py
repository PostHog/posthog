"""Tests for the poll-duckgres-usage activity.

The activity is the whole poll: fetch → replace-upsert (commit) → ack. Two
custody rules are load-bearing:

- **commit before ack** — rows must be persisted before we ack, because the ack
  tells duckgres to delete the acked buckets.
- **record before ack** — we persist the watermark we're about to ack in the
  same transaction as the rows, so a failed ack leaves our record *ahead* of
  duckgres (the benign "duckgres behind" direction) rather than behind it.

The recorded watermark is then cross-checked against duckgres's own cursor
(`watermark_low`) on the next pull: if duckgres is *ahead* of our record it has
deleted buckets we have no record of processing — a possible hole — so we
persist what we got, alert, and refuse to ack until it's reconciled.

Client calls are mocked; the mirror tables are real.
"""

import datetime as dt
from decimal import Decimal

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from asgiref.sync import sync_to_async

from posthog.ducklake.models import DuckgresDailyStorageUsage, DuckgresDailyUsage, DuckgresUsageCursor
from posthog.temporal.duckgres_usage.activities import poll_duckgres_usage
from posthog.temporal.duckgres_usage.client import DuckgresBillingAPIError, StorageRow, UsageResponse, UsageRow
from posthog.temporal.duckgres_usage.types import PollDuckgresUsageInputs

ORG = "018f0000-0000-0000-0000-000000000000"


def _row(date: dt.date, cpu_seconds: int = 100) -> UsageRow:
    return UsageRow(
        date=date,
        org_id=ORG,
        team_id=42,
        query_source="standard",
        cpu=Decimal("8"),
        mem_gib=Decimal("16"),
        cpu_seconds=cpu_seconds,
        memory_seconds=800,
    )


def _storage_row(date: dt.date, gib_seconds: str = "360000") -> StorageRow:
    return StorageRow(date=date, org_id=ORG, team_id=42, gib_seconds=Decimal(gib_seconds))


CLOSED_DAY_RESPONSE = UsageResponse(
    # Window spans closed day 6 + open day 7: day 6 should be acked.
    watermark_low=dt.datetime(2026, 7, 5, 23, 59, 59, tzinfo=dt.UTC),
    watermark_high=dt.datetime(2026, 7, 7, 12, 39, tzinfo=dt.UTC),
    rows=[_row(dt.date(2026, 7, 6)), _row(dt.date(2026, 7, 7))],
)

OPEN_DAY_RESPONSE = UsageResponse(
    # Steady state: only the open day in the window, nothing new closed.
    watermark_low=dt.datetime(2026, 7, 6, 23, 59, 59, tzinfo=dt.UTC),
    watermark_high=dt.datetime(2026, 7, 7, 12, 39, tzinfo=dt.UTC),
    rows=[_row(dt.date(2026, 7, 7))],
)

TWO_FAMILY_RESPONSE = UsageResponse(
    # Yesterday (day 6, closed) + today (day 7, open), both compute and storage.
    watermark_low=dt.datetime(2026, 7, 5, 23, 59, 59, tzinfo=dt.UTC),
    watermark_high=dt.datetime(2026, 7, 7, 12, 39, tzinfo=dt.UTC),
    rows=[_row(dt.date(2026, 7, 6)), _row(dt.date(2026, 7, 7))],
    storage_rows=[_storage_row(dt.date(2026, 7, 6)), _storage_row(dt.date(2026, 7, 7))],
)

DAY_6_END = dt.datetime(2026, 7, 6, 23, 59, 59, tzinfo=dt.UTC)

# ORM access from the async test bodies must hop to a sync thread.
usage_count = sync_to_async(lambda: DuckgresDailyUsage.objects.count())
storage_count = sync_to_async(lambda: DuckgresDailyStorageUsage.objects.count())
cursor_exists = sync_to_async(lambda: DuckgresUsageCursor.objects.exists())
get_cursor_watermark = sync_to_async(lambda: DuckgresUsageCursor.objects.get(pk=1).last_acked_watermark)
usage_dates = sync_to_async(lambda: sorted(DuckgresDailyUsage.objects.values_list("date", flat=True)))
storage_dates = sync_to_async(lambda: sorted(DuckgresDailyStorageUsage.objects.values_list("date", flat=True)))


@sync_to_async
def create_cursor(last_acked: dt.datetime) -> None:
    DuckgresUsageCursor.objects.create(pk=1, last_acked_watermark=last_acked)


def _patched(response, ack_side_effect=None):
    """Standard patch bundle: configured, given response, capturable ack + capture_exception + logger."""
    ack = patch("posthog.temporal.duckgres_usage.activities.ack_usage", side_effect=ack_side_effect)
    return (
        patch("posthog.temporal.duckgres_usage.activities.is_configured", return_value=True),
        patch("posthog.temporal.duckgres_usage.activities.fetch_usage", return_value=response),
        ack,
        patch("posthog.temporal.duckgres_usage.activities.capture_exception"),
        patch("posthog.temporal.duckgres_usage.activities.logger", MagicMock(ainfo=AsyncMock())),
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_upserts_and_acks_when_a_day_closed(activity_environment) -> None:
    is_conf, fetch, ack, _cap, _log = _patched(CLOSED_DAY_RESPONSE)
    with is_conf, fetch, ack as mock_ack, _cap, _log:
        result = await activity_environment.run(poll_duckgres_usage, PollDuckgresUsageInputs())

    assert await usage_count() == 2
    mock_ack.assert_called_once_with(DAY_6_END)
    assert result.rows_written == 2
    assert result.acked_watermark == DAY_6_END.isoformat()
    assert result.watermark_hole is False
    assert await get_cursor_watermark() == DAY_6_END


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_does_not_ack_when_nothing_closed(activity_environment) -> None:
    is_conf, fetch, ack, _cap, _log = _patched(OPEN_DAY_RESPONSE)
    with is_conf, fetch, ack as mock_ack, _cap, _log:
        result = await activity_environment.run(poll_duckgres_usage, PollDuckgresUsageInputs())

    assert await usage_count() == 1
    mock_ack.assert_not_called()
    assert result.acked_watermark is None
    assert not await cursor_exists()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_records_watermark_before_ack_so_failed_ack_is_recoverable(activity_environment) -> None:
    # Record-before-ack: the watermark is committed with the rows, so an ack
    # that fails afterwards leaves the record AHEAD of duckgres (benign "behind"
    # next pull), not behind it. Rows persist; the error surfaces for retry.
    is_conf, fetch, ack, _cap, _log = _patched(CLOSED_DAY_RESPONSE, ack_side_effect=DuckgresBillingAPIError("boom"))
    with is_conf, fetch, ack, _cap, _log:
        with pytest.raises(DuckgresBillingAPIError):
            await activity_environment.run(poll_duckgres_usage, PollDuckgresUsageInputs())

    assert await usage_count() == 2
    assert await get_cursor_watermark() == DAY_6_END  # recorded before the ack was attempted


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_skips_when_not_configured(activity_environment) -> None:
    with (
        patch("posthog.temporal.duckgres_usage.activities.is_configured", return_value=False),
        patch("posthog.temporal.duckgres_usage.activities.fetch_usage") as mock_fetch,
    ):
        result = await activity_environment.run(poll_duckgres_usage, PollDuckgresUsageInputs())

    assert result.skipped is True
    mock_fetch.assert_not_called()
    assert await usage_count() == 0


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_halts_and_alerts_on_watermark_hole(activity_environment) -> None:
    # Our record says we acked day 4's end, but duckgres now serves a window
    # starting at day 5's end — it advanced its cursor and deleted buckets past
    # anything we recorded processing. Possible lost usage: persist what we got,
    # alert, and DO NOT ack (don't delete more while we're inconsistent).
    await create_cursor(dt.datetime(2026, 7, 4, 23, 59, 59, tzinfo=dt.UTC))

    is_conf, fetch, ack, cap, _log = _patched(CLOSED_DAY_RESPONSE)
    with is_conf, fetch, ack as mock_ack, cap as mock_capture, _log:
        result = await activity_environment.run(poll_duckgres_usage, PollDuckgresUsageInputs())

    assert result.watermark_hole is True
    assert result.acked_watermark is None
    assert await usage_count() == 2  # still persisted
    mock_ack.assert_not_called()  # did NOT ack
    mock_capture.assert_called_once()  # surfaced to error tracking
    # Record untouched — we never acked, so it must not advance.
    assert await get_cursor_watermark() == dt.datetime(2026, 7, 4, 23, 59, 59, tzinfo=dt.UTC)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_logs_benign_and_acks_when_duckgres_is_behind(activity_environment) -> None:
    # Our record is ahead of duckgres (e.g. a prior ack didn't stick): duckgres
    # re-serves data we already processed. Idempotent — log it, keep acking.
    await create_cursor(dt.datetime(2026, 7, 7, 23, 59, 59, tzinfo=dt.UTC))

    is_conf, fetch, ack, cap, _log = _patched(CLOSED_DAY_RESPONSE)
    with is_conf, fetch, ack as mock_ack, cap as mock_capture, _log as mock_logger:
        result = await activity_environment.run(poll_duckgres_usage, PollDuckgresUsageInputs())

    assert result.watermark_hole is False
    mock_ack.assert_called_once_with(DAY_6_END)  # not halted
    mock_capture.assert_not_called()  # benign, not an error
    warned = [c.args[0] for c in mock_logger.warning.call_args_list]
    assert "duckgres_usage_watermark_behind" in warned


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_in_sync_cursor_does_not_warn_and_advances(activity_environment) -> None:
    await create_cursor(CLOSED_DAY_RESPONSE.watermark_low)

    is_conf, fetch, ack, cap, _log = _patched(CLOSED_DAY_RESPONSE)
    with is_conf, fetch, ack, cap as mock_capture, _log as mock_logger:
        await activity_environment.run(poll_duckgres_usage, PollDuckgresUsageInputs())

    warned = [c.args[0] for c in mock_logger.warning.call_args_list]
    assert "duckgres_usage_watermark_behind" not in warned
    mock_capture.assert_not_called()
    assert await get_cursor_watermark() == DAY_6_END


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_two_families_two_days_upserts_both_and_acks_only_closed_day(activity_environment) -> None:
    # The scenario spelled out: yesterday (closed) + today (open), both compute
    # and storage, land as separate day rows per family; only yesterday acks.
    is_conf, fetch, ack, _cap, _log = _patched(TWO_FAMILY_RESPONSE)
    with is_conf, fetch, ack as mock_ack, _cap, _log:
        result = await activity_environment.run(poll_duckgres_usage, PollDuckgresUsageInputs())

    assert result.rows_written == 4  # 2 compute + 2 storage
    assert await usage_dates() == [dt.date(2026, 7, 6), dt.date(2026, 7, 7)]
    assert await storage_dates() == [dt.date(2026, 7, 6), dt.date(2026, 7, 7)]
    mock_ack.assert_called_once_with(DAY_6_END)
    assert await get_cursor_watermark() == DAY_6_END
