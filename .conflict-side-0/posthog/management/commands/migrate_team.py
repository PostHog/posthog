import logging
import datetime as dt

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from posthog.batch_exports.models import BATCH_EXPORT_INTERVALS
from posthog.batch_exports.service import backfill_export, disable_and_delete_export, sync_batch_export
from posthog.models import BatchExport, BatchExportBackfill, BatchExportDestination, BatchExportRun, Team
from posthog.temporal.common.client import sync_connect

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

EXPORT_NAME = "PostHog HTTP Migration"
VALID_INTERVALS = {i[0] for i in BATCH_EXPORT_INTERVALS}
REGION_URLS = {
    "us": "https://app.posthog.com/batch",
    "eu": "https://eu.posthog.com/batch",
}


class Command(BaseCommand):
    help = "Creates an HTTP batch export for a team to migrate data to another PostHog instance, \
            or another team within the same instance."

    def add_arguments(self, parser):
        parser.add_argument("--team-id", default=None, type=int, help="Team ID to migrate from (on this instance)")
        parser.add_argument("--interval", default=None, type=str, help="Interval to use for the batch export")
        parser.add_argument(
            "--start-at",
            default=None,
            type=str,
            help="Timestamp to start the backfill from in UTC, 'YYYY-MM-DD' or 'YYYY-MM-DD HH:MM:SS'",
        )
        parser.add_argument(
            "--delete-existing", default=False, type=bool, help="Delete existing batch export if it exists"
        )
        parser.add_argument("--dest-token", default=None, type=str, help="Destination Project API Key (token)")
        parser.add_argument("--dest-region", default=None, type=str, help="Destination region")
        parser.add_argument(
            "--end-days-from-now",
            default=30,
            type=int,
            help="Number of days from now to automatically end the ongoing export at, the default is usually fine",
        )
        parser.add_argument(
            "--exclude-event",
            "-e",
            nargs="+",
            dest="exclude_events",
            required=False,
            type=str,
            help="Event to exclude from migration. Can be used multiple times.",
        )
        parser.add_argument(
            "--include-event",
            "-i",
            nargs="+",
            dest="include_events",
            required=False,
            type=str,
            help="Event to include in migration. Can be used multiple times.",
        )

    def handle(self, **options):
        team_id = options["team_id"]
        interval = options["interval"]
        start_at = options["start_at"]
        dest_token = options["dest_token"]
        dest_region = options["dest_region"]
        verbose = options["verbosity"] > 1
        exclude_events = options["exclude_events"]
        include_events = options["include_events"]

        create_args = [
            interval,
            start_at,
            dest_token,
            dest_region,
        ]
        create_requested = any(create_args)

        if not team_id:
            raise CommandError("source Team ID is required")

        team = Team.objects.select_related("organization").get(id=team_id)

        display(
            "Team",
            name=team.name,
            organization=team.organization.name,
        )

        try:
            existing_export: BatchExport = BatchExport.objects.get(
                team=team, destination__type="HTTP", name=EXPORT_NAME, deleted=False
            )
            is_existing_export = True

            display_existing(existing_export=existing_export, verbose=verbose)

            if options["delete_existing"]:
                result = input("Enter [y] to continue deleting the existing migration (Ctrl+C to cancel) ")
                if result.lower() != "y":
                    raise CommandError("Didn't receive 'y', exiting")
                print()  # noqa: T201

                disable_and_delete_export(existing_export)
                is_existing_export = False
                display("Deleted existing batch export and backfill")
        except BatchExport.DoesNotExist:
            is_existing_export = False
            display("No existing migration was found")
        except BatchExport.MultipleObjectsReturned:
            raise CommandError(
                "More than one existing migration found! This should never happen if the management command is used, we don't know enough to proceed"
            )

        if not create_requested:
            # User didn't provide any arguments to create a migration, so they must have just wanted
            # to check the status and/or delete the existing migration.
            return
        elif is_existing_export:
            display(
                "Existing migration job already exists and it wasn't deleted, exiting without creating a new batch export"
            )
            return

        end_days_from_now = options["end_days_from_now"]

        create_migration(
            team_id=team_id,
            interval=interval,
            start_at=start_at,
            dest_token=dest_token,
            dest_region=dest_region,
            end_days_from_now=end_days_from_now,
            exclude_events=exclude_events,
            include_events=include_events,
        )


def display_existing(*, existing_export: BatchExport, verbose: bool):
    existing_backfill = BatchExportBackfill.objects.get(batch_export=existing_export)
    most_recent_run = BatchExportRun.objects.filter(batch_export=existing_export).order_by("-created_at").first()

    if verbose:
        display(
            "Existing migration batch export (verbose details)",
            batch_export_id=existing_export.id,
            paused=existing_export.paused,
            interval=existing_export.interval,
            created_at=existing_export.created_at,
            last_updated_at=existing_export.last_updated_at,
            exclude_events=existing_export.destination.config.get("exclude_events", []),
            include_events=existing_export.destination.config.get("include_events", []),
        )
        display(
            "Existing migration backfill (verbose details)",
            backfill_id=existing_backfill.id,
            status=existing_backfill.status,
            start_at=existing_backfill.start_at,
            created_at=existing_backfill.created_at,
            last_updated_at=existing_backfill.last_updated_at,
        )

    if not most_recent_run:
        display("No batch export runs found, is the migration brand new?")
    else:
        most_recent_completed_run = (
            BatchExportRun.objects.filter(batch_export=existing_export, status=BatchExportRun.Status.COMPLETED)
            .order_by("-finished_at")
            .first()
        )

        if most_recent_completed_run:
            data_start_at = existing_backfill.start_at
            data_end_at = most_recent_completed_run.data_interval_end
            display(
                "Found an existing migration, range of data migrated:",
                start=data_start_at,
                end=data_end_at,
                interval=existing_export.interval,
            )
            if existing_export.paused:
                display("The batch export backfill is still catching up to realtime")
            else:
                display(
                    "The batch export is unpaused, meaning the primary backfill completed and this is now in realtime export mode",
                )

        if not most_recent_completed_run or verbose:
            display(
                "Most recent run (verbose details)",
                run_id=most_recent_run.id,
                status=most_recent_run.status,
                error=most_recent_run.latest_error,
                data_interval_start=most_recent_run.data_interval_start,
                data_interval_end=most_recent_run.data_interval_end,
                created_at=most_recent_run.created_at,
                last_updated_at=most_recent_run.last_updated_at,
            )


def create_migration(
    *,
    team_id: int,
    interval: str,
    start_at: str,
    dest_token: str,
    dest_region: str,
    end_days_from_now: int,
    include_events: list[str] | None = None,
    exclude_events: list[str] | None = None,
):
    if interval not in VALID_INTERVALS:
        raise CommandError("invalid interval, choices are: {}".format(VALID_INTERVALS))

    if not dest_token.startswith("phc_"):
        raise CommandError("invalid destination token, must start with 'phc_'")

    dest_region = dest_region.lower()
    if dest_region not in REGION_URLS:
        raise CommandError("invalid destination region, choices are: 'us', 'eu'")
    url = REGION_URLS[dest_region]

    try:
        start_at_datetime = parse_to_utc(start_at)
    except ValueError as e:
        raise CommandError("couldn't parse start_at: {}".format(e))

    display(
        "Creating migration",
        interval=interval,
        start_at=start_at_datetime,
        dest_token=dest_token,
        dest_region=dest_region,
        url=url,
        exclude_events=exclude_events,
        include_events=include_events,
    )
    result = input("Enter [y] to continue creating a new migration (Ctrl+C to cancel) ")
    if result.lower() != "y":
        raise CommandError("Didn't receive 'y', exiting")
    print()  # noqa: T201

    now = dt.datetime.now(dt.UTC)
    # This is a precaution so we don't accidentally leave the export running indefinitely.
    end_at = now + dt.timedelta(days=end_days_from_now)

    destination = BatchExportDestination(
        type=BatchExportDestination.Destination.HTTP,
        config={"url": url, "token": dest_token, "include_events": include_events, "exclude_events": exclude_events},
    )
    batch_export = BatchExport(
        team_id=team_id,
        destination=destination,
        name=EXPORT_NAME,
        interval=interval,
        paused=True,
        end_at=end_at,
    )
    sync_batch_export(batch_export, created=True)

    with transaction.atomic():
        destination.save()
        batch_export.save()

    temporal = sync_connect()
    backfill_id = backfill_export(temporal, str(batch_export.pk), team_id, start_at_datetime, end_at=None)
    display("Backfill started", batch_export_id=batch_export.id, backfill_id=backfill_id)


def display(message, **kwargs):
    print(message)  # noqa: T201
    for key, value in kwargs.items():
        if isinstance(value, dt.datetime):
            value = value.strftime("%Y-%m-%d %H:%M:%S")
        print(f"  {key} = {value}")  # noqa: T201
    print()  # noqa: T201


def parse_to_utc(date_str: str) -> dt.datetime:
    try:
        parsed_datetime = dt.datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        try:
            parsed_datetime = dt.datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            raise ValueError("Invalid date format. Expected 'YYYY-MM-DD' or 'YYYY-MM-DD HH:MM:SS'.")

    utc_datetime = parsed_datetime.replace(tzinfo=dt.UTC)
    return utc_datetime
