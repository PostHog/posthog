import asyncio
from datetime import UTC, datetime, timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

import temporalio.client

from posthog.batch_exports.models import BatchExport, BatchExportRun
from posthog.temporal.common.client import connect

from products.batch_exports.backend.service import align_timestamp_to_interval

# Statuses that count as "covered" — the run either succeeded or is still in progress
COVERED_STATUSES = [
    BatchExportRun.Status.COMPLETED,
    BatchExportRun.Status.RUNNING,
    BatchExportRun.Status.STARTING,
    # Not sure what this actually means but keep it just in case?
    BatchExportRun.Status.CONTINUED_AS_NEW,
]


def ensure_aware(dt: datetime) -> datetime:
    """Treat naive datetimes as UTC."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


def format_export(export: BatchExport) -> str:
    return f"{export.id} (interval={export.interval}, destination={export.destination.type}, team_id={export.team_id})"


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


def get_backfill_bounds(
    export: BatchExport, first_interval_end: datetime, last_interval_end: datetime
) -> tuple[datetime, datetime]:
    """Create a backfill window around data_interval_end values.

    Temporal's ScheduleBackfill triggers all schedule actions within [start_at, end_at].
    The padding on `last_interval_end` uses the export's jitter — wide enough for Temporal
    to recognize the action, but narrow enough to avoid triggering an extra run.

    For example, if we wanted to backfill the data interval from 2026-03-08 10:00:00 to 2026-03-09 10:00:00,
    we would use the following bounds:
    - start_at: 2026-03-09 10:00:00
    - end_at: 2026-03-09 10:00:00 + export.jitter
    This would trigger a single workflow run in Temporal.
    """
    return (first_interval_end, last_interval_end + export.jitter)


def get_batch_exports(
    batch_export_id: str | None = None,
    destination_type: str | None = None,
    team_id: int | None = None,
    model: str | None = None,
) -> list[BatchExport]:
    """Fetch batch exports to check, filtering out deleted/paused ones."""
    filters: dict = {"deleted": False, "paused": False}
    if batch_export_id:
        filters["id"] = batch_export_id
    if destination_type:
        filters["destination__type"] = destination_type
    if team_id:
        filters["team_id"] = team_id
    if model:
        filters["model"] = model
    return list(BatchExport.objects.filter(**filters).select_related("destination"))


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


class Command(BaseCommand):
    help = "Find and backfill missing batch export runs via Temporal schedule backfills"

    def add_arguments(self, parser):
        parser.add_argument(
            "--lookback-hours",
            type=int,
            default=None,
            help="Hours to look back for missing runs (default: 48, mutually exclusive with --start)",
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
            "--no-confirm",
            action="store_true",
            default=False,
            help="Skip the confirmation prompt before starting backfills",
        )
        parser.add_argument(
            "--overlap-policy",
            type=str.upper,
            choices=["BUFFER_ALL", "ALLOW_ALL"],
            default="BUFFER_ALL",
            help=(
                "Temporal schedule overlap policy for backfills (default: BUFFER_ALL). "
                "Only use ALLOW_ALL when: (1) you are backfilling only the events model, "
                "and (2) there are not many backfill intervals to run"
            ),
        )

    def _resolve_window(self, options: dict) -> tuple[datetime, datetime]:
        has_start = options["start"] is not None
        has_end = options["end"] is not None
        has_lookback = options["lookback_hours"] is not None

        if has_end and not has_start:
            raise CommandError("--end requires --start")
        if has_start and has_lookback:
            raise CommandError("--start/--end and --lookback-hours are mutually exclusive")
        if has_lookback and options["lookback_hours"] <= 0:
            raise CommandError("--lookback-hours must be a positive integer")

        now = timezone.now()

        if has_start:
            start = ensure_aware(options["start"])
            end = ensure_aware(options["end"]) if has_end else now
            if start >= end:
                raise CommandError("--start must be before --end")
            return start, end

        lookback_hours = has_lookback and options["lookback_hours"] or 48
        return now - timedelta(hours=lookback_hours), now

    async def _backfill_export(
        self,
        client: temporalio.client.Client,
        export: BatchExport,
        missing_intervals: list[tuple],
        dry_run: bool,
        overlap_policy: temporalio.client.ScheduleOverlapPolicy,
        no_delay: bool = False,
    ) -> bool:
        """Trigger Temporal schedule backfills for the missing intervals of a single export.

        Returns True if backfills were triggered (or would be in dry-run mode), False if the schedule was not found.
        """
        batch_export_id = str(export.id)
        handle = client.get_schedule_handle(batch_export_id)

        try:
            await handle.describe()
        except temporalio.service.RPCError as err:
            self.stderr.write(
                self.style.WARNING(f"Schedule {batch_export_id} not found ({err.__class__.__name__}: {err}), skipping")
            )
            return False

        for overall_interval_start, overall_interval_end in missing_intervals:
            # We want to trigger backfills based on the interval_end values
            first_interval_end = next_interval_boundary(overall_interval_start, export)
            backfill_start, backfill_end = get_backfill_bounds(export, first_interval_end, overall_interval_end)

            if dry_run:
                self.stdout.write(
                    f"        Would backfill {overall_interval_start.isoformat()} -> {overall_interval_end.isoformat()}"
                )
            else:
                self.stdout.write(
                    f"        Backfilling {overall_interval_start.isoformat()} -> {overall_interval_end.isoformat()}"
                )
                backfill = temporalio.client.ScheduleBackfill(
                    start_at=backfill_start,
                    end_at=backfill_end,
                    overlap=overlap_policy,
                )
                await handle.backfill(backfill)
                if not no_delay:
                    await asyncio.sleep(2)

        return True

    async def _run_backfills(
        self,
        missing_by_export: list[tuple[BatchExport, list[tuple]]],
        dry_run: bool,
        overlap_policy: temporalio.client.ScheduleOverlapPolicy,
        no_delay: bool = False,
    ) -> tuple[int, int]:
        """Connect to Temporal and trigger backfills for all missing intervals.

        Returns (total_backfills, failures).
        """
        client = await connect(
            settings.TEMPORAL_HOST,
            settings.TEMPORAL_PORT,
            settings.TEMPORAL_NAMESPACE,
            client_cert=settings.TEMPORAL_CLIENT_CERT,
            client_key=settings.TEMPORAL_CLIENT_KEY,
        )

        total_backfills = 0
        failures = 0

        if dry_run:
            self.stdout.write("\n[DRY RUN] Would trigger backfills for following export(s):")
        else:
            self.stdout.write(f"\nTriggering backfills using {overlap_policy.name} overlap policy...")

        for export, missing_intervals in missing_by_export:
            self.stdout.write(f"  - {format_export(export)}: {len(missing_intervals)} interval(s) missing")

            success = await self._backfill_export(
                client=client,
                export=export,
                missing_intervals=missing_intervals,
                dry_run=dry_run,
                overlap_policy=overlap_policy,
                no_delay=no_delay,
            )
            if success:
                total_backfills += len(missing_intervals)
            else:
                failures += 1

        return total_backfills, failures

    def handle(self, **options):
        start, end = self._resolve_window(options)

        exports = get_batch_exports(
            batch_export_id=options["batch_export_id"],
            destination_type=options["destination_type"],
            team_id=options["team_id"],
            model=options["model"],
        )

        if not exports:
            self.stdout.write(self.style.WARNING("No batch exports found"))
            return

        self.stdout.write(
            f"\nChecking {len(exports)} batch export(s) for missing runs ({start.isoformat()} to {end.isoformat()})",
            ending="\n\n",
        )

        missing_by_export = find_missing_intervals(exports, start, end)

        if not missing_by_export:
            self.stdout.write(self.style.SUCCESS("No missing runs found"))
            return

        total_missing = sum(len(m) for _, m in missing_by_export)
        self.stdout.write(f"Found {total_missing} missing interval(s) across {len(missing_by_export)} export(s):")
        preview_limit = 10
        for export, intervals in missing_by_export[:preview_limit]:
            first_start = intervals[0][0].isoformat()
            last_end = intervals[-1][1].isoformat()
            self.stdout.write(f"  {format_export(export)}: {len(intervals)} gap(s), {first_start} -> {last_end}")
        remaining = len(missing_by_export) - preview_limit
        if remaining > 0:
            self.stdout.write(f"  ... and {remaining} more export(s)")

        if not options["dry_run"] and not options["no_confirm"]:
            confirm = input(f"\nProceed with backfilling {total_missing} interval(s)? [y/N] ")
            if confirm.lower() != "y":
                self.stdout.write(self.style.WARNING("Aborted"))
                return

        overlap_policy = temporalio.client.ScheduleOverlapPolicy[options["overlap_policy"]]

        total_backfills, failures = asyncio.run(
            self._run_backfills(missing_by_export, options["dry_run"], overlap_policy, options["no_delay"]),
        )

        if not options["dry_run"]:
            self.stdout.write(
                self.style.SUCCESS(f"\nBackfill complete: {total_backfills} backfills, {failures} failures")
            )
