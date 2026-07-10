"""Tests for the poll and ack activities.

The poll activity fetches, persists, and *decides* the ack — it records the
watermark to ack (in the same transaction as the rows, record-before-ack) but
does not perform it; the workflow runs a separate ack activity for that. Custody
rules under test:

- The poll withholds the ack (returns no `ack_watermark`, doesn't advance the
  cursor) on a detected hole (`watermark_low > recorded`), a parse failure, or a
  row dated outside the window, so duckgres keeps data this pull didn't fully
  capture.
- The benign "duckgres behind" direction still yields an `ack_watermark`.
- The ack activity is a thin, idempotent POST.

Client calls are mocked; the mirror tables and cursor are real.
"""

import datetime as dt
from decimal import Decimal

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from asgiref.sync import sync_to_async

from posthog.ducklake.models import DuckgresDailyStorageUsage, DuckgresDailyUsage, DuckgresUsageCursor
from posthog.temporal.duckgres_usage.activities import ack_duckgres_usage, poll_duckgres_usage
from posthog.temporal.duckgres_usage.client import StorageRow, UsageResponse, UsageRow
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

PARSE_FAILURE_RESPONSE = UsageResponse(
    # A day closed (would normally ack), but one row failed to parse.
    watermark_low=dt.datetime(2026, 7, 5, 23, 59, 59, tzinfo=dt.UTC),
    watermark_high=dt.datetime(2026, 7, 7, 12, 39, tzinfo=dt.UTC),
    rows=[_row(dt.date(2026, 7, 6))],
    unparsed_row_count=1,
    unparsed_row_sample={"date": "2026-07-06", "team_id": "not-a-number"},
)

OUT_OF_WINDOW_RESPONSE = UsageResponse(
    # A day closed (would normally ack), but duckgres also served a row dated
    # day 3 — below its own cursor, outside the window [day 6, day 7].
    watermark_low=dt.datetime(2026, 7, 5, 23, 59, 59, tzinfo=dt.UTC),
    watermark_high=dt.datetime(2026, 7, 7, 12, 39, tzinfo=dt.UTC),
    rows=[_row(dt.date(2026, 7, 3)), _row(dt.date(2026, 7, 6))],
)

DAY_6_END = dt.datetime(2026, 7, 6, 23, 59, 59, tzinfo=dt.UTC)

# ORM access from the async test bodies must hop to a sync thread.
usage_count = sync_to_async(lambda: DuckgresDailyUsage.objects.count())
cursor_exists = sync_to_async(lambda: DuckgresUsageCursor.objects.exists())
get_cursor_watermark = sync_to_async(lambda: DuckgresUsageCursor.objects.get(singleton=1).last_acked_watermark)
usage_dates = sync_to_async(lambda: sorted(DuckgresDailyUsage.objects.values_list("date", flat=True)))
storage_dates = sync_to_async(lambda: sorted(DuckgresDailyStorageUsage.objects.values_list("date", flat=True)))


@sync_to_async
def create_cursor(last_acked: dt.datetime) -> None:
    DuckgresUsageCursor.objects.create(singleton=1, last_acked_watermark=last_acked)


def _patched(response):
    """Poll never acks, so no ack_usage patch — just config, response, capture, logger."""
    return (
        patch("posthog.temporal.duckgres_usage.activities.is_configured", return_value=True),
        patch("posthog.temporal.duckgres_usage.activities.fetch_usage", return_value=response),
        patch("posthog.temporal.duckgres_usage.activities.capture_exception"),
        patch("posthog.temporal.duckgres_usage.activities.logger", MagicMock(ainfo=AsyncMock())),
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_persists_and_returns_ack_watermark_when_a_day_closed(activity_environment) -> None:
    is_conf, fetch, cap, log = _patched(CLOSED_DAY_RESPONSE)
    with is_conf, fetch, cap, log:
        result = await activity_environment.run(poll_duckgres_usage, PollDuckgresUsageInputs())

    assert await usage_count() == 2
    assert result.rows_written == 2
    assert result.ack_watermark == DAY_6_END.isoformat()  # for the workflow to ack
    assert result.watermark_hole is False
    assert await get_cursor_watermark() == DAY_6_END  # recorded before the ack (record-before-ack)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_no_ack_watermark_when_nothing_closed(activity_environment) -> None:
    is_conf, fetch, cap, log = _patched(OPEN_DAY_RESPONSE)
    with is_conf, fetch, cap, log:
        result = await activity_environment.run(poll_duckgres_usage, PollDuckgresUsageInputs())

    assert await usage_count() == 1
    assert result.ack_watermark is None
    assert not await cursor_exists()


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
async def test_withholds_ack_and_alerts_on_watermark_hole(activity_environment) -> None:
    # Duckgres serves a window starting past our record — it deleted buckets we
    # never processed. Persist what we got, alert, and DON'T offer an ack.
    await create_cursor(dt.datetime(2026, 7, 4, 23, 59, 59, tzinfo=dt.UTC))

    is_conf, fetch, cap, log = _patched(CLOSED_DAY_RESPONSE)
    with is_conf, fetch, cap as mock_capture, log:
        result = await activity_environment.run(poll_duckgres_usage, PollDuckgresUsageInputs())

    assert result.watermark_hole is True
    assert result.ack_watermark is None  # withheld
    assert await usage_count() == 2  # still persisted
    mock_capture.assert_called_once()
    # Record untouched — we didn't ack, so it must not advance.
    assert await get_cursor_watermark() == dt.datetime(2026, 7, 4, 23, 59, 59, tzinfo=dt.UTC)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_withholds_ack_and_alerts_on_parse_failure(activity_environment) -> None:
    # A row failed to parse: persist the good ones, alert, and withhold the ack
    # so duckgres keeps the source data until the upstream cause is fixed.
    is_conf, fetch, cap, log = _patched(PARSE_FAILURE_RESPONSE)
    with is_conf, fetch, cap as mock_capture, log:
        result = await activity_environment.run(poll_duckgres_usage, PollDuckgresUsageInputs())

    assert result.unparsed_row_count == 1
    assert result.ack_watermark is None  # withheld despite a closed day
    assert await usage_count() == 1  # the good row persisted
    mock_capture.assert_called_once()
    assert not await cursor_exists()  # nothing acked, nothing recorded


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_withholds_ack_and_alerts_on_out_of_window_rows(activity_environment) -> None:
    # Duckgres served a row dated below its cursor (outside the window). It's
    # dropped, not persisted — and the ack is withheld so it can't delete that
    # row's source bucket, even though a day closed.
    is_conf, fetch, cap, log = _patched(OUT_OF_WINDOW_RESPONSE)
    with is_conf, fetch, cap as mock_capture, log:
        result = await activity_environment.run(poll_duckgres_usage, PollDuckgresUsageInputs())

    assert result.out_of_window_dropped == 1
    assert result.ack_watermark is None  # withheld
    assert await usage_count() == 1  # only the in-window day 6 row persisted
    assert await usage_dates() == [dt.date(2026, 7, 6)]
    mock_capture.assert_called_once()
    assert not await cursor_exists()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_benign_when_duckgres_is_behind_still_offers_ack(activity_environment) -> None:
    # Our record is ahead of duckgres (a prior ack didn't stick): it re-serves
    # data we already have. Idempotent — log it, still offer the ack.
    await create_cursor(dt.datetime(2026, 7, 7, 23, 59, 59, tzinfo=dt.UTC))

    is_conf, fetch, cap, log = _patched(CLOSED_DAY_RESPONSE)
    with is_conf, fetch, cap as mock_capture, log as mock_logger:
        result = await activity_environment.run(poll_duckgres_usage, PollDuckgresUsageInputs())

    assert result.watermark_hole is False
    assert result.ack_watermark == DAY_6_END.isoformat()  # not withheld
    mock_capture.assert_not_called()  # benign, not an error
    warned = [c.args[0] for c in mock_logger.warning.call_args_list]
    assert "duckgres_usage_watermark_behind" in warned


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_in_sync_cursor_does_not_warn_and_advances(activity_environment) -> None:
    await create_cursor(CLOSED_DAY_RESPONSE.watermark_low)

    is_conf, fetch, cap, log = _patched(CLOSED_DAY_RESPONSE)
    with is_conf, fetch, cap as mock_capture, log as mock_logger:
        await activity_environment.run(poll_duckgres_usage, PollDuckgresUsageInputs())

    warned = [c.args[0] for c in mock_logger.warning.call_args_list]
    assert "duckgres_usage_watermark_behind" not in warned
    mock_capture.assert_not_called()
    assert await get_cursor_watermark() == DAY_6_END


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_two_families_two_days_persist_and_offer_ack_of_closed_day(activity_environment) -> None:
    is_conf, fetch, cap, log = _patched(TWO_FAMILY_RESPONSE)
    with is_conf, fetch, cap, log:
        result = await activity_environment.run(poll_duckgres_usage, PollDuckgresUsageInputs())

    assert result.rows_written == 4  # 2 compute + 2 storage
    assert await usage_dates() == [dt.date(2026, 7, 6), dt.date(2026, 7, 7)]
    assert await storage_dates() == [dt.date(2026, 7, 6), dt.date(2026, 7, 7)]
    assert result.ack_watermark == DAY_6_END.isoformat()
    assert await get_cursor_watermark() == DAY_6_END


@pytest.mark.asyncio
async def test_ack_activity_acks_the_parsed_watermark(activity_environment) -> None:
    with patch("posthog.temporal.duckgres_usage.activities.ack_usage") as mock_ack:
        await activity_environment.run(ack_duckgres_usage, DAY_6_END.isoformat())

    mock_ack.assert_called_once_with(DAY_6_END)
