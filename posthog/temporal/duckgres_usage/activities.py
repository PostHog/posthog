"""The poll-duckgres-usage activity: fetch → replace-upsert (commit) → ack.

One activity on purpose: the rows never cross an activity boundary (Temporal
payload limits never see them), and the commit-before-ack ordering — the
custody handoff, duckgres deletes acked buckets — lives in one readable
function. Every step is idempotent (replace-upsert, re-ack), so the whole
activity retries safely from the top.
"""

import structlog
from asgiref.sync import sync_to_async
from temporalio import activity

from posthog.ducklake.models import DuckgresUsageCursor
from posthog.sync import database_sync_to_async
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.duckgres_usage.acking import day_boundary_ack
from posthog.temporal.duckgres_usage.client import UsageResponse, ack_usage, fetch_usage, is_configured
from posthog.temporal.duckgres_usage.staging import replace_window
from posthog.temporal.duckgres_usage.types import PollDuckgresUsageInputs, PollDuckgresUsageResult

logger = structlog.get_logger(__name__)


@activity.defn(name="poll-duckgres-usage")
async def poll_duckgres_usage(inputs: PollDuckgresUsageInputs) -> PollDuckgresUsageResult:
    async with Heartbeater():
        if not is_configured():
            await logger.ainfo("duckgres_usage_poll_skipped_not_configured")
            return PollDuckgresUsageResult(skipped=True)

        response = await sync_to_async(fetch_usage)()

        await database_sync_to_async(_warn_on_desync)(response)

        rows_written = await database_sync_to_async(replace_window)(response)

        # Rows are committed — only now may custody move.
        ack_at = day_boundary_ack(watermark_low=response.watermark_low, watermark_high=response.watermark_high)
        if ack_at is not None:
            await sync_to_async(ack_usage)(ack_at)
            await database_sync_to_async(_record_ack)(ack_at)

        await logger.ainfo(
            "duckgres_usage_polled",
            rows_written=rows_written,
            row_count=len(response.rows),
            watermark_low=response.watermark_low.isoformat(),
            watermark_high=response.watermark_high.isoformat(),
            acked_watermark=ack_at.isoformat() if ack_at else None,
        )
        return PollDuckgresUsageResult(
            rows_written=rows_written,
            watermark_low=response.watermark_low.isoformat(),
            watermark_high=response.watermark_high.isoformat(),
            acked_watermark=ack_at.isoformat() if ack_at else None,
        )


def _warn_on_desync(response: UsageResponse) -> None:
    """Advisory cross-check of duckgres's cursor against our last recorded ack.

    Duckgres is authoritative; a mismatch means its cursor moved without us
    (reset, foreign acker) and is worth an alert, but processing continues —
    replace semantics absorb re-served windows, and skipped-ahead data is
    already gone.
    """
    cursor = DuckgresUsageCursor.objects.filter(pk=1).first()
    if cursor is not None and cursor.last_acked_watermark != response.watermark_low:
        logger.warning(
            "duckgres_usage_watermark_desync",
            local_last_acked=cursor.last_acked_watermark.isoformat(),
            server_watermark_low=response.watermark_low.isoformat(),
        )


def _record_ack(acked_watermark) -> None:
    DuckgresUsageCursor.objects.update_or_create(pk=1, defaults={"last_acked_watermark": acked_watermark})
