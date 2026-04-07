import asyncio
import logging
from datetime import UTC, datetime, timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

import structlog
import temporalio.client

from posthog.batch_exports.models import BatchExport, BatchExportRun
from posthog.temporal.common.client import connect

from products.batch_exports.backend.service import align_timestamp_to_interval

logger = structlog.get_logger(__name__)


# Statuses that count as "covered" — the run either succeeded or is still in progress
COVERED_STATUSES = [
    BatchExportRun.Status.COMPLETED,
    BatchExportRun.Status.RUNNING,
    BatchExportRun.Status.STARTING,
    # Not sure what this actually means but keep it just in case?
    BatchExportRun.Status.CONTINUED_AS_NEW,
]


def next_interval_boundary(current: datetime, export: BatchExport) -> datetime:
    """Advance to the next interval boundary, respecting DST in local time.

    For hourly/sub-hourly intervals, a fixed timedelta is correct since DST
    doesn't affect the interval length. For daily/weekly, we add the nominal
    timedelta plus a 2-hour buffer to land somewhere in the next interval
    (even on 25-hour fall-back days), then re-align to snap to the exact
    local-time boundary.
    """
    if export.interval == "hour" or export.interval.startswith("every"):
        return current + export.interval_time_delta

    rough_next = current + export.interval_time_delta + timedelta(hours=2)
    return align_timestamp_to_interval(rough_next, export)


def get_backfill_bounds(interval: str, first_end: datetime, last_end: datetime) -> tuple[datetime, datetime]:
    """Create bounds around a range of data_interval_ends so the schedule backfill covers all runs.

    The end padding needs to be wide enough for Temporal to recognize the last schedule tick
    within the window, but narrow enough to avoid triggering an extra run beyond the range.
    """
    if interval == "hour":
        padding = timedelta(minutes=30)
    elif interval == "day":
        padding = timedelta(hours=2)
    elif interval == "week":
        padding = timedelta(hours=6)
    elif interval.startswith("every"):
        padding = timedelta(minutes=2)
    else:
        raise ValueError(f"Unsupported interval: '{interval}'")
    return (first_end, last_end + padding)


def get_batch_exports(
    batch_export_id: str | None = None,
    destination_type: str | None = None,
    team_id: int | None = None,
    model: str | None = None,
) -> list[BatchExport]:
    """Fetch batch exports to check, filtering out deleted/paused ones."""
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
        return [export]

    filters: dict = {"deleted": False, "paused": False}
    if destination_type:
        filters["destination__type"] = destination_type
    if team_id:
        filters["team_id"] = team_id
    if model:
        filters["model"] = model
    return list(BatchExport.objects.filter(**filters).select_related("destination", "team"))


def find_missing_intervals(
    exports: list[BatchExport],
    start: datetime,
    end: datetime,
) -> list[tuple[BatchExport, list[tuple[datetime, datetime]]]]:
    """Find gaps in run history for the given batch exports.

    Walks each export's expected schedule within the [start, end] window, identifies
    intervals that have no run with a covered status, and merges continuous gaps into
    single ranges so they can be backfilled in fewer operations.
    """
    results = []

    for export in exports:
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
            interval_start = next_interval_boundary(interval_start, export)

        # Collect individual missing intervals, then merge continuous ones
        missing_individual: list[tuple[datetime, datetime]] = []
        while True:
            interval_end = next_interval_boundary(interval_start, export)
            if interval_end > end:
                break
            if interval_end not in covered_run_ends:
                missing_individual.append((interval_start, interval_end))
            interval_start = interval_end

        # Merge continuous intervals into single ranges
        merged: list[tuple[datetime, datetime]] = []
        for gap_start, gap_end in missing_individual:
            if merged and gap_start == merged[-1][1]:
                merged[-1] = (merged[-1][0], gap_end)
            else:
                merged.append((gap_start, gap_end))

        if merged:
            results.append((export, merged))

    return results


async def backfill_export(
    client: temporalio.client.Client,
    export: BatchExport,
    missing_intervals: list[tuple],
    dry_run: bool,
    overlap_policy: temporalio.client.ScheduleOverlapPolicy = temporalio.client.ScheduleOverlapPolicy.BUFFER_ALL,
    no_delay: bool = False,
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
            backfill_start, backfill_end = get_backfill_bounds(export.interval, interval_start, interval_end)
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
                overlap=overlap_policy,
            )
            await handle.backfill(backfill)
            if not no_delay:
                await asyncio.sleep(2)

        count += 1

    return count


async def run_backfills(
    missing_by_export: list[tuple[BatchExport, list[tuple]]],
    dry_run: bool,
    overlap_policy: temporalio.client.ScheduleOverlapPolicy = temporalio.client.ScheduleOverlapPolicy.BUFFER_ALL,
    no_delay: bool = False,
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
            f"Batch export '{export.name}' (id={export.id}, team={export.team_id}, "
            f"interval={export.interval}) — {len(missing_intervals)} missing"
        )

        count = await backfill_export(
            client=client,
            export=export,
            missing_intervals=missing_intervals,
            dry_run=dry_run,
            overlap_policy=overlap_policy,
            no_delay=no_delay,
        )
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
        parser.add_argument(
            "--team-id",
            type=int,
            default=None,
            help="Only check batch exports for a specific team",
        )
        parser.add_argument(
            "--model",
            type=str,
            choices=["events", "persons", "sessions"],
            default=None,
            help="Filter by export model (e.g. events, persons, sessions)",
        )
        parser.add_argument(
            "--no-delay",
            action="store_true",
            default=False,
            help="Skip the 2-second delay between backfill requests",
        )
        parser.add_argument(
            "--overlap-policy",
            type=str,
            choices=["buffer_all", "allow_all"],
            default="buffer_all",
            help=(
                "Temporal schedule overlap policy for backfills (default: buffer_all). "
                "Only use allow_all when: (1) you are backfilling only the events model, "
                "and (2) there are not many backfill intervals to run"
            ),
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

        exports = get_batch_exports(
            batch_export_id=options["batch_export_id"],
            destination_type=options["destination_type"],
            team_id=options["team_id"],
            model=options["model"],
        )

        if not exports:
            logger.info("No batch exports found")
            return

        logger.info(
            f"Checking {len(exports)} batch export(s) for missing runs ({start.isoformat()} to {end.isoformat()})"
        )

        missing_by_export = find_missing_intervals(exports, start, end)

        if not missing_by_export:
            logger.info("No missing runs found")
            return

        total_missing = sum(len(m) for _, m in missing_by_export)
        logger.info(f"Found {total_missing} missing interval(s) across {len(missing_by_export)} export(s)")

        if not options["dry_run"]:
            confirm = input(f"Proceed with backfilling {total_missing} interval(s)? [y/N] ")
            if confirm.lower() != "y":
                logger.info("Aborted")
                return

        overlap_policy_map = {
            "buffer_all": temporalio.client.ScheduleOverlapPolicy.BUFFER_ALL,
            "allow_all": temporalio.client.ScheduleOverlapPolicy.ALLOW_ALL,
        }
        overlap_policy = overlap_policy_map[options["overlap_policy"]]

        total_backfills, failed_exports = asyncio.run(
            run_backfills(missing_by_export, options["dry_run"], overlap_policy, options["no_delay"]),
        )

        if not options["dry_run"]:
            logger.info(f"Backfill complete: {total_backfills} backfills, {failed_exports} failed exports")
