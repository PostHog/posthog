import asyncio
import logging
from datetime import UTC, datetime, timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

import temporalio.client

from posthog.batch_exports.models import BatchExport, BatchExportRun
from posthog.temporal.common.client import connect

from products.batch_exports.backend.service import align_timestamp_to_interval

logger = logging.getLogger(__name__)


# Statuses that count as "covered" — the run either succeeded or is still in progress
COVERED_STATUSES = [
    BatchExportRun.Status.COMPLETED,
    BatchExportRun.Status.RUNNING,
    BatchExportRun.Status.STARTING,
    # Not sure what this actually means but keep it just in case?
    BatchExportRun.Status.CONTINUED_AS_NEW,
]


def get_backfill_bounds(interval: str, data_interval_end) -> tuple:
    """Create tight bounds around a data_interval_end so the schedule backfill triggers exactly one run.

    The bounds need to be wide enough for Temporal to recognize one schedule tick
    within the window, but narrow enough to avoid triggering multiple runs.
    """
    if interval == "hour":
        end_at = data_interval_end + timedelta(minutes=30)
    elif interval == "day":
        end_at = data_interval_end + timedelta(hours=2)
    elif interval == "week":
        end_at = data_interval_end + timedelta(hours=6)
    elif interval.startswith("every"):
        end_at = data_interval_end + timedelta(minutes=2)
    else:
        raise ValueError(f"Unsupported interval: '{interval}'")
    return (data_interval_end, end_at)


def find_missing_runs(
    start: datetime,
    end: datetime,
    batch_export_id: str | None = None,
    destination_type: str | None = None,
) -> list[tuple[BatchExport, list[tuple]]]:
    """Find batch exports with gaps in their run history.

    Walks each export's expected schedule within the [start, end] window and identifies
    intervals that have no run with a covered status.
    """
    if batch_export_id:
        try:
            export = BatchExport.objects.select_related("destination", "team").get(id=batch_export_id)
        except BatchExport.DoesNotExist:
            logger.warning(f"Batch export {batch_export_id} not found")
            return []
        if export.deleted:
            logger.warning(f"Batch export {batch_export_id} is deleted, skipping")
            return []
        if export.paused:
            logger.warning(f"Batch export {batch_export_id} is paused, skipping")
            return []
        exports = [export]
    else:
        filters: dict = {"deleted": False, "paused": False}
        if destination_type:
            filters["destination__type"] = destination_type
        exports = BatchExport.objects.filter(**filters).select_related("destination", "team")

    count = len(exports) if isinstance(exports, list) else exports.count()
    logger.info(f"Checking {count} batch export(s) for missing runs ({start.isoformat()} to {end.isoformat()})")

    results = []

    for export in exports:
        interval_delta = export.interval_time_delta

        covered_run_ends = set(
            BatchExportRun.objects.filter(
                batch_export=export,
                data_interval_start__gte=start,
                data_interval_end__lte=end,
                status__in=COVERED_STATUSES,
            ).values_list("data_interval_end", flat=True)
        )

        # Align to the start of the interval containing `start`.
        # If `start` is mid-interval, advance to the next boundary
        # so we only consider complete intervals.
        interval_start = align_timestamp_to_interval(start, export)
        if interval_start < start:
            interval_start += interval_delta

        missing = []
        while interval_start + interval_delta <= end:
            interval_end = interval_start + interval_delta
            if interval_end not in covered_run_ends:
                missing.append((interval_start, interval_end))
            interval_start = interval_end

        if missing:
            results.append((export, missing))

    return results


async def backfill_export(
    client: temporalio.client.Client,
    export: BatchExport,
    missing_intervals: list[tuple],
    dry_run: bool,
) -> int:
    """Trigger Temporal schedule backfills for the missing intervals of a single export.

    Returns the number of backfills triggered (or that would be triggered in dry-run mode).
    """
    batch_export_id = str(export.id)
    handle = client.get_schedule_handle(batch_export_id)

    try:
        await handle.describe()
    except Exception as err:
        logger.warning(f"Schedule {batch_export_id} not found ({err.__class__.__name__}: {err}), skipping")
        return 0

    count = 0
    for interval_start, interval_end in missing_intervals:
        try:
            backfill_start, backfill_end = get_backfill_bounds(export.interval, interval_end)
        except ValueError as err:
            logger.warning(f"Unsupported interval for {batch_export_id} ({err}), skipping export")
            return count

        if dry_run:
            logger.info(f"  [DRY RUN] Would backfill {interval_start.isoformat()} -> {interval_end.isoformat()}")
        else:
            logger.info(f"  Backfilling {interval_start.isoformat()} -> {interval_end.isoformat()}")
            backfill = temporalio.client.ScheduleBackfill(
                start_at=backfill_start,
                end_at=backfill_end,
                overlap=temporalio.client.ScheduleOverlapPolicy.BUFFER_ALL,
            )
            await handle.backfill(backfill)
            await asyncio.sleep(2)

        count += 1

    return count


async def run_backfills(
    missing_by_export: list[tuple[BatchExport, list[tuple]]],
    dry_run: bool,
) -> tuple[int, int]:
    """Connect to Temporal and trigger backfills for all missing intervals.

    Returns (total_backfills, failed_exports).
    """
    client = await connect(
        settings.TEMPORAL_HOST,
        settings.TEMPORAL_PORT,
        settings.TEMPORAL_NAMESPACE,
        client_cert=settings.TEMPORAL_CLIENT_CERT,
        client_key=settings.TEMPORAL_CLIENT_KEY,
    )

    total_backfills = 0
    failed_exports = 0

    for export, missing_intervals in missing_by_export:
        logger.info(
            f"{export.name} (id={export.id}, team={export.team_id}, "
            f"interval={export.interval}) — {len(missing_intervals)} missing"
        )

        count = await backfill_export(client, export, missing_intervals, dry_run)
        if count == 0 and len(missing_intervals) > 0:
            failed_exports += 1
        total_backfills += count

    return total_backfills, failed_exports


class Command(BaseCommand):
    help = "Find and backfill missing batch export runs via Temporal schedule backfills"

    def add_arguments(self, parser):
        parser.add_argument(
            "--lookback-hours",
            type=int,
            default=None,
            help="Hours to look back for missing runs (default: 48, ignored if --start is provided)",
        )
        parser.add_argument(
            "--start",
            type=datetime.fromisoformat,
            default=None,
            help="Start of the search window as an ISO-8601 datetime (e.g. 2026-03-10T00:00:00Z)",
        )
        parser.add_argument(
            "--end",
            type=datetime.fromisoformat,
            default=None,
            help="End of the search window as an ISO-8601 datetime (defaults to now if --start is provided)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Only print what would be backfilled without triggering backfills",
        )
        parser.add_argument(
            "--batch-export-id",
            type=str,
            default=None,
            help="Only check a specific batch export by ID",
        )
        parser.add_argument(
            "--destination-type",
            type=str,
            default=None,
            help="Filter by destination type (e.g. Databricks, S3)",
        )

    @staticmethod
    def _ensure_aware(dt: datetime) -> datetime:
        """Treat naive datetimes as UTC."""
        if dt.tzinfo is None:
            return dt.replace(tzinfo=UTC)
        return dt

    def _resolve_window(self, options: dict) -> tuple[datetime, datetime]:
        has_start = options["start"] is not None
        has_end = options["end"] is not None
        has_lookback = options["lookback_hours"] is not None

        if has_end and not has_start:
            raise CommandError("--end requires --start")
        if has_start and has_lookback:
            raise CommandError("--start/--end and --lookback-hours are mutually exclusive")

        now = timezone.now()

        if has_start:
            start = self._ensure_aware(options["start"])
            end = self._ensure_aware(options["end"]) if has_end else now
            if start >= end:
                raise CommandError("--start must be before --end")
            return start, end

        lookback_hours = has_lookback and options["lookback_hours"] or 48
        return now - timedelta(hours=lookback_hours), now

    def handle(self, **options):
        logger.setLevel(logging.INFO)

        start, end = self._resolve_window(options)

        missing_by_export = find_missing_runs(
            start=start,
            end=end,
            batch_export_id=options["batch_export_id"],
            destination_type=options["destination_type"],
        )

        if not missing_by_export:
            logger.info("No missing runs found")
            return

        total_missing = sum(len(m) for _, m in missing_by_export)
        logger.info(f"Found {total_missing} missing interval(s) across {len(missing_by_export)} export(s)")

        if options["dry_run"]:
            self.stdout.write("[DRY RUN MODE]")

        total_backfills, failed_exports = asyncio.run(
            run_backfills(missing_by_export, options["dry_run"]),
        )

        prefix = "[DRY RUN] " if options["dry_run"] else ""
        logger.info(f"{prefix}Backfill complete: {total_backfills} backfills, {failed_exports} failed exports")
