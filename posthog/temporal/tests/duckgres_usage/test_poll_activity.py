"""Tests for the poll-duckgres-usage activity.

The activity is the whole poll: fetch → replace-upsert (commit) → ack. The
ordering is the custody boundary — rows must be committed before the ack hands
custody to us (duckgres deletes acked buckets). Client calls are mocked; the
staging table is real.
"""

import datetime as dt
from decimal import Decimal

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from asgiref.sync import sync_to_async

from posthog.ducklake.models import DuckgresDailyUsage, DuckgresUsageCursor
from posthog.temporal.duckgres_usage.activities import poll_duckgres_usage
from posthog.temporal.duckgres_usage.client import DuckgresBillingAPIError, UsageResponse, UsageRow
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

DAY_6_END = dt.datetime(2026, 7, 6, 23, 59, 59, tzinfo=dt.UTC)

# ORM access from the async test bodies must hop to a sync thread.
usage_count = sync_to_async(lambda: DuckgresDailyUsage.objects.count())
cursor_exists = sync_to_async(lambda: DuckgresUsageCursor.objects.exists())
get_cursor_watermark = sync_to_async(lambda: DuckgresUsageCursor.objects.get(pk=1).last_acked_watermark)


@sync_to_async
def create_cursor(last_acked: dt.datetime) -> None:
    DuckgresUsageCursor.objects.create(pk=1, last_acked_watermark=last_acked)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_upserts_and_acks_when_a_day_closed(activity_environment) -> None:
    with (
        patch("posthog.temporal.duckgres_usage.activities.is_configured", return_value=True),
        patch("posthog.temporal.duckgres_usage.activities.fetch_usage", return_value=CLOSED_DAY_RESPONSE),
        patch("posthog.temporal.duckgres_usage.activities.ack_usage") as mock_ack,
    ):
        result = await activity_environment.run(poll_duckgres_usage, PollDuckgresUsageInputs())

    assert await usage_count() == 2
    mock_ack.assert_called_once_with(DAY_6_END)
    assert result.rows_written == 2
    assert result.acked_watermark == DAY_6_END.isoformat()
    assert await get_cursor_watermark() == DAY_6_END


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_does_not_ack_when_nothing_closed(activity_environment) -> None:
    with (
        patch("posthog.temporal.duckgres_usage.activities.is_configured", return_value=True),
        patch("posthog.temporal.duckgres_usage.activities.fetch_usage", return_value=OPEN_DAY_RESPONSE),
        patch("posthog.temporal.duckgres_usage.activities.ack_usage") as mock_ack,
    ):
        result = await activity_environment.run(poll_duckgres_usage, PollDuckgresUsageInputs())

    assert await usage_count() == 1
    mock_ack.assert_not_called()
    assert result.acked_watermark is None
    assert not await cursor_exists()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_rows_survive_a_failed_ack(activity_environment) -> None:
    # Commit-then-ack: the ack failing after the commit must leave the rows in
    # place and surface the error (the activity retry re-pulls and re-acks —
    # both idempotent).
    with (
        patch("posthog.temporal.duckgres_usage.activities.is_configured", return_value=True),
        patch("posthog.temporal.duckgres_usage.activities.fetch_usage", return_value=CLOSED_DAY_RESPONSE),
        patch(
            "posthog.temporal.duckgres_usage.activities.ack_usage",
            side_effect=DuckgresBillingAPIError("ack failed"),
        ),
    ):
        with pytest.raises(DuckgresBillingAPIError):
            await activity_environment.run(poll_duckgres_usage, PollDuckgresUsageInputs())

    assert await usage_count() == 2
    # The local cursor only records SUCCESSFUL acks.
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
async def test_warns_on_watermark_desync(activity_environment) -> None:
    # Our record says we acked day 4's end, but duckgres serves a window
    # starting at day 5's end: someone or something moved the server cursor.
    # Advisory only — duckgres is authoritative, processing continues.
    await create_cursor(dt.datetime(2026, 7, 4, 23, 59, 59, tzinfo=dt.UTC))

    with (
        patch("posthog.temporal.duckgres_usage.activities.is_configured", return_value=True),
        patch("posthog.temporal.duckgres_usage.activities.fetch_usage", return_value=CLOSED_DAY_RESPONSE),
        patch("posthog.temporal.duckgres_usage.activities.ack_usage"),
        patch("posthog.temporal.duckgres_usage.activities.logger", MagicMock(ainfo=AsyncMock())) as mock_logger,
    ):
        result = await activity_environment.run(poll_duckgres_usage, PollDuckgresUsageInputs())

    assert result.rows_written == 2
    warned_events = [call.args[0] for call in mock_logger.warning.call_args_list]
    assert "duckgres_usage_watermark_desync" in warned_events


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_in_sync_cursor_does_not_warn_and_advances(activity_environment) -> None:
    await create_cursor(CLOSED_DAY_RESPONSE.watermark_low)

    with (
        patch("posthog.temporal.duckgres_usage.activities.is_configured", return_value=True),
        patch("posthog.temporal.duckgres_usage.activities.fetch_usage", return_value=CLOSED_DAY_RESPONSE),
        patch("posthog.temporal.duckgres_usage.activities.ack_usage"),
        patch("posthog.temporal.duckgres_usage.activities.logger", MagicMock(ainfo=AsyncMock())) as mock_logger,
    ):
        await activity_environment.run(poll_duckgres_usage, PollDuckgresUsageInputs())

    warned_events = [call.args[0] for call in mock_logger.warning.call_args_list]
    assert "duckgres_usage_watermark_desync" not in warned_events
    assert await get_cursor_watermark() == DAY_6_END
