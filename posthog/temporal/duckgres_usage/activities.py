"""The poll-duckgres-usage activity: fetch → replace-upsert (commit) → ack.

One activity on purpose: the rows never cross an activity boundary (Temporal
payload limits never see them), and two custody rules live in one readable
function:

- **commit before ack** — rows are persisted before we ack, because the ack
  tells duckgres to delete the acked buckets.
- **record before ack** — the watermark we're about to ack is written in the
  same transaction as the rows, so a failed ack leaves our record *ahead* of
  duckgres (the benign "duckgres behind" direction) rather than behind it.

On each pull we cross-check our recorded watermark against duckgres's own
cursor (`watermark_low`). If duckgres is *ahead* of our record it has deleted
buckets we have no record of processing — a possible hole in billable usage —
so we persist what we got, alert, and refuse to ack until it's reconciled.
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


@activity.defn(name="poll-duckgres-usage")
async def poll_duckgres_usage(inputs: PollDuckgresUsageInputs) -> PollDuckgresUsageResult:
    async with Heartbeater():
        if not is_configured():
            await logger.ainfo("duckgres_usage_poll_skipped_not_configured")
            return PollDuckgresUsageResult(skipped=True)

        response = await sync_to_async(fetch_usage)()

        recorded = await database_sync_to_async(_read_recorded_watermark)()
        hole = recorded is not None and response.watermark_low > recorded
        if recorded is not None and response.watermark_low < recorded:
            # Duckgres re-serves data we already acked past; replace semantics
            # absorb it idempotently. Worth noting, not halting.
            logger.warning(
                "duckgres_usage_watermark_behind",
                recorded=recorded.isoformat(),
                server_watermark_low=response.watermark_low.isoformat(),
            )

        ack_at = day_boundary_ack(watermark_low=response.watermark_low, watermark_high=response.watermark_high)
        should_ack = ack_at is not None and not hole

        # One transaction: persist the mirror rows and — record-before-ack — the
        # watermark we're about to hand to duckgres. If the ack below fails, our
        # record is ahead of duckgres, i.e. the benign "behind" direction.
        rows_written = await database_sync_to_async(_persist)(response, ack_at if should_ack else None)

        acked_watermark = ack_at.isoformat() if (should_ack and ack_at is not None) else None

        if hole:
            capture_exception(
                DuckgresWatermarkHole(
                    f"duckgres watermark_low {response.watermark_low.isoformat()} is ahead of last acked "
                    f"{recorded.isoformat() if recorded else None}; persisted this window but did not ack"
                )
            )
        elif should_ack and ack_at is not None:
            await sync_to_async(ack_usage)(ack_at)

        await logger.ainfo(
            "duckgres_usage_polled",
            rows_written=rows_written,
            row_count=len(response.rows),
            storage_row_count=len(response.storage_rows),
            watermark_low=response.watermark_low.isoformat(),
            watermark_high=response.watermark_high.isoformat(),
            acked_watermark=acked_watermark,
            watermark_hole=hole,
        )
        return PollDuckgresUsageResult(
            rows_written=rows_written,
            watermark_low=response.watermark_low.isoformat(),
            watermark_high=response.watermark_high.isoformat(),
            acked_watermark=acked_watermark,
            watermark_hole=hole,
        )


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
