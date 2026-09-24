import logging
import datetime as dt
from collections.abc import Sequence

from django.core.management.base import BaseCommand, CommandError

from posthog.models import Team

from products.batch_exports.backend.facade import api as batch_exports_api
from products.batch_exports.backend.facade.contracts import BatchExportBackfillSummary, BatchExportDetail

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

EXPORT_NAME = "PostHog HTTP Migration"
HTTP_DESTINATION_TYPE = "HTTP"
DATA_START_UNBOUNDED = "the start of the team's data"
VALID_INTERVALS = set(batch_exports_api.list_supported_intervals())
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
        parser.add_argument("--dest-token", default=None, type=str, help="Destination project token")
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
            existing_export = batch_exports_api.get_batch_export_by_name(team.id, EXPORT_NAME, HTTP_DESTINATION_TYPE)
        except batch_exports_api.MultipleBatchExportsError:
            raise CommandError(
                "More than one existing migration found! This should never happen if the management command is used, we don't know enough to proceed"
            )

        if existing_export is None:
            is_existing_export = False
            display("No existing migration was found")
        else:
            is_existing_export = True

            display_existing(existing_export=existing_export, verbose=verbose)

            if options["delete_existing"]:
                result = input("Enter [y] to continue deleting the existing migration (Ctrl+C to cancel) ")
                if result.lower() != "y":
                    raise CommandError("Didn't receive 'y', exiting")
                print()  # noqa: T201

                batch_exports_api.delete_batch_export(existing_export.id, team.id)
                is_existing_export = False
                display("Deleted existing batch export and backfill")

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


def get_migrated_data_start(backfills: Sequence[BatchExportBackfillSummary]) -> dt.datetime | str | None:
    """Return where the migrated data begins, from the backfills that did not fail.

    A later backfill can cover a narrower range than the one the command started, so the
    earliest start wins. A backfill with no start exports all data, so the range is then
    unbounded. None means that every backfill failed.
    """
    starts = [
        backfill.adjusted_start_at or backfill.start_at
        for backfill in backfills
        if backfill.status not in batch_exports_api.FAILED_BACKFILL_STATUSES
    ]
    if not starts:
        return None
    if any(start is None for start in starts):
        return DATA_START_UNBOUNDED
    return min(start for start in starts if start is not None)


def display_existing(*, existing_export: BatchExportDetail, verbose: bool):
    existing_backfills = batch_exports_api.list_backfills_for_export(existing_export.id, existing_export.team_id)
    if not existing_backfills:
        raise CommandError("The existing migration has no backfill, so we don't know enough to proceed")
    most_recent_run = batch_exports_api.get_latest_run(existing_export.id, existing_export.team_id)

    if verbose:
        display(
            "Existing migration batch export (verbose details)",
            batch_export_id=existing_export.id,
            paused=existing_export.paused,
            interval=existing_export.interval,
            created_at=existing_export.created_at,
            last_updated_at=existing_export.last_updated_at,
            exclude_events=list(existing_export.exclude_events),
            include_events=list(existing_export.include_events),
        )
        for existing_backfill in existing_backfills:
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
        most_recent_completed_run = batch_exports_api.get_latest_completed_run(
            existing_export.id, existing_export.team_id
        )

        if most_recent_completed_run:
            data_start_at = get_migrated_data_start(existing_backfills)
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

    batch_export = batch_exports_api.create_batch_export(
        team_id,
        name=EXPORT_NAME,
        destination_type=HTTP_DESTINATION_TYPE,
        destination_config={
            "url": url,
            "token": dest_token,
            "include_events": include_events,
            "exclude_events": exclude_events,
        },
        interval=interval,
        paused=True,
        end_at=end_at,
    )

    backfill_id = batch_exports_api.backfill_batch_export(batch_export.id, team_id, start_at_datetime, end_at=None)
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
