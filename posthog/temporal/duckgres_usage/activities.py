"""Activities for the duckgres usage poll.

Two activities, split on purpose:

- **poll_duckgres_usage** — fetch the un-acked window, persist it to the mirror,
  and *decide* the ack, but don't perform it. The fetched rows can be tens of MB
  at scale, so they can't cross the workflow boundary as an activity return
  value — fetch and persist must live together here.
- **ack_duckgres_usage** — perform the ack POST. Separate so a transient ack
  failure retries just the POST, not the whole (large) fetch+persist.

Two custody rules hold across the split:

- **commit before ack** — the poll commits the rows before it returns, and the
  workflow only acks after that, so duckgres is never told to delete unpersisted data.
- **record before ack** — the poll writes the watermark it will ack in the same
  transaction as the rows, so an ack that never lands (crash, exhausted retries)
  leaves our record *ahead* of duckgres — the benign "duckgres behind" direction
  that self-heals (re-acks) on the next pull.

Each pull cross-checks our recorded watermark against duckgres's own cursor
(`watermark_low`). If duckgres is *ahead* of our record it has deleted buckets we
have no record of processing — a possible hole in billable usage — so we persist
what we got, alert, and withhold the ack until it's reconciled. An unparseable
row is treated the same way: persist the good rows, alert, withhold the ack so
duckgres keeps the source data until the upstream cause is fixed.
"""

import datetime as dt

from django.db import transaction

import structlog
from asgiref.sync import sync_to_async
from temporalio import activity

from posthog.ducklake.models import DuckgresUsageCursor
from posthog.exceptions_capture import capture_exception
from posthog.sync import database_sync_to_async
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.duckgres_usage.acking import day_boundary_ack
from posthog.temporal.duckgres_usage.client import UsageResponse, ack_usage, fetch_usage, is_configured
from posthog.temporal.duckgres_usage.mirror import replace_window
from posthog.temporal.duckgres_usage.types import PollDuckgresUsageInputs, PollDuckgresUsageResult

logger = structlog.get_logger(__name__)


class DuckgresWatermarkHole(Exception):
    """Duckgres's cursor is ahead of our last recorded ack — it deleted buckets
    past what we have any record of processing, so billable usage may be lost."""


class DuckgresRowParseError(Exception):
    """One or more duckgres usage rows could not be parsed and were dropped."""


@activity.defn(name="poll-duckgres-usage")
async def poll_duckgres_usage(inputs: PollDuckgresUsageInputs) -> PollDuckgresUsageResult:
    async with Heartbeater():
        if not is_configured():
            await logger.ainfo("duckgres_usage_poll_skipped_not_configured")
            return PollDuckgresUsageResult(skipped=True)

        response = await sync_to_async(fetch_usage)()

        recorded = await database_sync_to_async(_read_recorded_watermark)()
        hole = recorded is not None and response.watermark_low > recorded
        parse_failure = response.unparsed_row_count > 0
        if recorded is not None and response.watermark_low < recorded:
            # Duckgres re-serves data we already acked past; replace semantics
            # absorb it idempotently. Worth noting, not halting.
            logger.warning(
                "duckgres_usage_watermark_behind",
                recorded=recorded.isoformat(),
                server_watermark_low=response.watermark_low.isoformat(),
            )

        ack_at = day_boundary_ack(watermark_low=response.watermark_low, watermark_high=response.watermark_high)
        # Withhold the ack on a hole or a parse failure — acking would let
        # duckgres delete data this pull didn't fully capture.
        should_ack = ack_at is not None and not hole and not parse_failure
        ack_watermark = ack_at.isoformat() if (should_ack and ack_at is not None) else None

        # One transaction: persist the mirror rows and — record-before-ack — the
        # watermark the workflow will ack next.
        rows_written = await database_sync_to_async(_persist)(response, ack_at if should_ack else None)

        if hole:
            capture_exception(
                DuckgresWatermarkHole(
                    f"duckgres watermark_low {response.watermark_low.isoformat()} is ahead of last acked "
                    f"{recorded.isoformat() if recorded else None}; persisted this window but withheld the ack"
                )
            )
        if parse_failure:
            capture_exception(
                DuckgresRowParseError(
                    f"dropped {response.unparsed_row_count} unparseable duckgres usage row(s) and withheld "
                    f"the ack; sample: {response.unparsed_row_sample}"
                )
            )

        await logger.ainfo(
            "duckgres_usage_polled",
            rows_written=rows_written,
            row_count=len(response.rows),
            storage_row_count=len(response.storage_rows),
            watermark_low=response.watermark_low.isoformat(),
            watermark_high=response.watermark_high.isoformat(),
            ack_watermark=ack_watermark,
            watermark_hole=hole,
            unparsed_row_count=response.unparsed_row_count,
        )
        return PollDuckgresUsageResult(
            rows_written=rows_written,
            watermark_low=response.watermark_low.isoformat(),
            watermark_high=response.watermark_high.isoformat(),
            ack_watermark=ack_watermark,
            watermark_hole=hole,
            unparsed_row_count=response.unparsed_row_count,
        )


@activity.defn(name="ack-duckgres-usage")
async def ack_duckgres_usage(ack_watermark: str) -> None:
    """Ack the watermark the poll activity committed. Its own activity so a
    transient failure retries just this POST. Idempotent on duckgres (re-acking
    the same watermark is a no-op)."""
    await sync_to_async(ack_usage)(dt.datetime.fromisoformat(ack_watermark))


def _read_recorded_watermark() -> dt.datetime | None:
    cursor = DuckgresUsageCursor.objects.first()
    return cursor.last_acked_watermark if cursor is not None else None


def _persist(response: UsageResponse, watermark_to_record: dt.datetime | None) -> int:
    with transaction.atomic():
        rows_written = replace_window(response)
        if watermark_to_record is not None:
            DuckgresUsageCursor.objects.update_or_create(
                singleton=1, defaults={"last_acked_watermark": watermark_to_record}
            )
    return rows_written
