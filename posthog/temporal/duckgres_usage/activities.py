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
import dataclasses

from django.db import transaction

import structlog
from asgiref.sync import sync_to_async
from temporalio import activity

from posthog.ducklake.models import DuckgresUsageCursor
from posthog.exceptions_capture import capture_exception
from posthog.sync import database_sync_to_async
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.duckgres_usage.acking import day_boundary_ack
from posthog.temporal.duckgres_usage.client import (
    UsageResponse,
    ack_usage,
    fetch_usage,
    is_configured,
    set_default_team,
)
from posthog.temporal.duckgres_usage.mirror import count_out_of_window_rows, replace_window
from posthog.temporal.duckgres_usage.team_resolution import resolve_billing_teams
from posthog.temporal.duckgres_usage.types import (
    PollDuckgresUsageInputs,
    PollDuckgresUsageResult,
    SetDuckgresDefaultTeamInputs,
)

logger = structlog.get_logger(__name__)


class DuckgresWatermarkHole(Exception):
    """Duckgres's cursor is ahead of our last recorded ack — it deleted buckets
    past what we have any record of processing, so billable usage may be lost."""


class DuckgresRowParseError(Exception):
    """One or more duckgres usage rows could not be parsed and were dropped."""


class DuckgresRowsOutsideWindow(Exception):
    """Duckgres served rows dated outside the ack window (at or below its own
    cursor). They were dropped, not persisted, so the ack is withheld — acking
    could delete their source buckets and permanently under-bill."""


class DuckgresUsageOrphanedTeam(Exception):
    """An org's managed-warehouse usage was under a deleted team and the org has
    no live team to re-attribute it to, so it was dropped. Unlike the anomalies
    above the ack still proceeds — re-pulling can't help a warehouse with no
    projects; the data is unattributable, not withheld."""


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
        out_of_window = count_out_of_window_rows(response)
        if recorded is not None and response.watermark_low < recorded:
            # Duckgres re-serves data we already acked past; replace semantics
            # absorb it idempotently. Worth noting, not halting.
            logger.warning(
                "duckgres_usage_watermark_behind",
                recorded=recorded.isoformat(),
                server_watermark_low=response.watermark_low.isoformat(),
            )

        ack_at = day_boundary_ack(watermark_low=response.watermark_low, watermark_high=response.watermark_high)
        # Withhold the ack on any anomaly — a hole, an unparseable row, or a row
        # dropped for being outside the window — since acking would let duckgres
        # delete data this pull didn't fully capture.
        should_ack = ack_at is not None and not hole and not parse_failure and out_of_window == 0
        ack_watermark = ack_at.isoformat() if (should_ack and ack_at is not None) else None

        # One transaction: persist the mirror rows and — record-before-ack — the
        # watermark the workflow will ack next. Record max(recorded, ack_at): in
        # the benign "duckgres behind" case ack_at can be older than what we've
        # already recorded, and regressing the cursor would make the next normal
        # pull read as a fake hole. The ack itself stays ack_at (idempotent).
        watermark_to_record = ack_at if should_ack else None
        if watermark_to_record is not None and recorded is not None:
            watermark_to_record = max(watermark_to_record, recorded)
        rows_written, orphaned_org_ids, default_team_repoints = await database_sync_to_async(_persist)(
            response, watermark_to_record
        )

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
        if out_of_window:
            capture_exception(
                DuckgresRowsOutsideWindow(
                    f"dropped {out_of_window} duckgres row(s) dated outside the ack window "
                    f"(watermark_low {response.watermark_low.isoformat()}) and withheld the ack"
                )
            )
        if orphaned_org_ids:
            capture_exception(
                DuckgresUsageOrphanedTeam(
                    f"dropped managed-warehouse usage for {len(orphaned_org_ids)} org(s) whose team was "
                    f"deleted with no live team to re-attribute to: {sorted(orphaned_org_ids)}"
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
            out_of_window_dropped=out_of_window,
            # A source-config mutation follows for each entry (repoint duckgres's
            # default team), so surface it: {org_id: elected_live_team}.
            default_team_repoints=default_team_repoints,
        )
        return PollDuckgresUsageResult(
            rows_written=rows_written,
            watermark_low=response.watermark_low.isoformat(),
            watermark_high=response.watermark_high.isoformat(),
            ack_watermark=ack_watermark,
            watermark_hole=hole,
            unparsed_row_count=response.unparsed_row_count,
            out_of_window_dropped=out_of_window,
            default_team_repoints=default_team_repoints,
        )


@activity.defn(name="ack-duckgres-usage")
async def ack_duckgres_usage(ack_watermark: str) -> None:
    """Ack the watermark the poll activity committed. Its own activity so a
    transient failure retries just this POST. Idempotent on duckgres (re-acking
    the same watermark is a no-op)."""
    await sync_to_async(ack_usage)(dt.datetime.fromisoformat(ack_watermark))


@activity.defn(name="set-duckgres-default-team")
async def set_duckgres_default_team(inputs: SetDuckgresDefaultTeamInputs) -> None:
    """Repoint one org's managed-warehouse default team in duckgres.

    Fired fire-and-forget by the poll workflow when duckgres is stamping a
    deleted default team. Its own activity so this control-plane write retries
    independently of the (large) pull; idempotent server-side, so retries and
    re-detections across polls are safe."""
    await sync_to_async(set_default_team)(inputs.org_id, inputs.team_id)


def _read_recorded_watermark() -> dt.datetime | None:
    cursor = DuckgresUsageCursor.objects.first()
    return cursor.last_acked_watermark if cursor is not None else None


def _persist(response: UsageResponse, watermark_to_record: dt.datetime | None) -> tuple[int, set[str], dict[str, int]]:
    # Re-attribute rows under a deleted team to a live team in the same org
    # before persisting, so the (live-teams-only) usage-report gather doesn't
    # drop them. Needs the Team table, so it runs here in the sync DB context.
    resolution = resolve_billing_teams(response.rows, response.storage_rows)
    resolved = dataclasses.replace(response, rows=resolution.compute_rows, storage_rows=resolution.storage_rows)
    with transaction.atomic():
        rows_written = replace_window(resolved)
        if watermark_to_record is not None:
            DuckgresUsageCursor.objects.update_or_create(
                singleton=1, defaults={"last_acked_watermark": watermark_to_record}
            )
    return rows_written, resolution.orphaned_org_ids, resolution.default_team_repoints
