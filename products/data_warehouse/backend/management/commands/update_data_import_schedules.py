import logging
import datetime as dt

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

import structlog

from products.data_warehouse.backend.logic.data_load.service import bulk_update_external_data_job_schedules
from products.warehouse_sources.backend.facade.models import (
    ExternalDataSchema,
    sync_frequency_to_sync_frequency_interval,
)

logger = structlog.get_logger(__name__)


def _get_external_data_schemas(**options) -> list[ExternalDataSchema]:
    filters_applied = False
    queryset = ExternalDataSchema.objects.filter(deleted=False)

    if options.get("external_data_source_id") is not None:
        queryset = queryset.filter(source_id=options["external_data_source_id"])
        filters_applied = True

    if options.get("team_ids") is not None:
        try:
            team_ids = [int(id) for id in options["team_ids"].split(",")]
        except ValueError:
            raise CommandError("team_ids must be a comma separated list of team IDs")
        queryset = queryset.filter(team_id__in=team_ids)
        filters_applied = True

    if options.get("exclude_team_ids") is not None:
        try:
            exclude_team_ids = [int(id) for id in options["exclude_team_ids"].split(",")]
        except ValueError:
            raise CommandError("exclude_team_ids must be a comma separated list of team IDs")
        # Check for overlap between include and exclude team IDs
        if options.get("team_ids") is not None:
            overlap = set(team_ids).intersection(exclude_team_ids)
            if overlap:
                overlap_str = ", ".join(map(str, overlap))
                raise CommandError(f"Team IDs {overlap_str} present in both include and exclude lists")
        queryset = queryset.exclude(team_id__in=exclude_team_ids)
        filters_applied = True

    if options.get("source_type") is not None:
        queryset = queryset.filter(source__source_type=options["source_type"])
        filters_applied = True

    if options.get("sync_type") is not None:
        queryset = queryset.filter(sync_type=options["sync_type"])
        filters_applied = True

    if options.get("sync_frequency") is not None:
        sync_frequency_interval = sync_frequency_to_sync_frequency_interval(options["sync_frequency"])
        queryset = queryset.filter(sync_frequency_interval=sync_frequency_interval)
        filters_applied = True

    if options.get("should_sync") is not None:
        queryset = queryset.filter(should_sync=options["should_sync"])
        filters_applied = True

    if options.get("updated_at_gt") is not None:
        try:
            updated_at_gt = dt.datetime.strptime(options["updated_at_gt"], "%Y-%m-%d").replace(tzinfo=dt.UTC)
        except ValueError:
            raise CommandError("updated_at_gt must be in the format YYYY-MM-DD")
        queryset = queryset.filter(updated_at__gt=updated_at_gt)
        filters_applied = True

    if options.get("updated_at_lt") is not None:
        try:
            updated_at_lt = dt.datetime.strptime(options["updated_at_lt"], "%Y-%m-%d").replace(tzinfo=dt.UTC)
        except ValueError:
            raise CommandError("updated_at_lt must be in the format YYYY-MM-DD")
        queryset = queryset.filter(updated_at__lt=updated_at_lt)
        filters_applied = True

    if not filters_applied:
        raise CommandError("Must call this command with at least one filter")

    return list(queryset)


class Command(BaseCommand):
    help = "Updates the Temporal schedules for data imports to ensure they are up to date"

    def add_arguments(self, parser):
        parser.add_argument(
            "--external-data-source-id", default=None, type=str, help="Single external data source ID to update"
        )
        parser.add_argument(
            "--team-ids",
            default=None,
            type=str,
            help="Comma separated list of team IDs for which to update all external data sources",
        )
        parser.add_argument(
            "--exclude-team-ids",
            default=None,
            type=str,
            help="Comma separated list of team IDs for which to exclude updating external data sources",
        )
        parser.add_argument(
            "--source-type", default=None, type=str, help="Update all external data sources for a given source type"
        )
        parser.add_argument(
            "--sync-type",
            default=None,
            type=str,
            choices=["full_refresh", "incremental"],
            help="Filter data schemas by sync type (full_refresh or incremental)",
        )
        parser.add_argument(
            "--sync-frequency",
            default=None,
            type=str,
            choices=["never", "5min", "30min", "1hour", "6hour", "12hour", "24hour", "7day", "30day"],
            help="Filter data schemas by sync frequency interval",
        )
        parser.add_argument(
            "--should-sync", default=None, type=bool, help="Filter data schemas by should sync value (True or False)"
        )
        parser.add_argument(
            "--updated-at-gt",
            default=None,
            type=str,
            help="Filter data schemas by updated at greater than (YYYY-MM-DD)",
        )
        parser.add_argument(
            "--updated-at-lt", default=None, type=str, help="Filter data schemas by updated at less than (YYYY-MM-DD)"
        )

    def handle(self, **options):
        logger.setLevel(logging.INFO)

        external_data_schemas = _get_external_data_schemas(**options)

        if len(external_data_schemas) == 0:
            raise CommandError("No external data schemas found")

        if not settings.TEST:
            confirm = input(
                f"\n\tWill update schedules for {len(external_data_schemas)} external data schemas. Proceed? (y/n) "
            )
            if confirm.strip().lower() != "y":
                logger.info("Aborting")
                return

        # `bulk_update_external_data_job_schedules` re-issues each schedule over a single
        # shared Temporal connection and runs the updates concurrently — far faster than
        # reconnecting per schema. It returns skipped (never-activated) schemas and failures
        # instead of raising, so one bad schema doesn't abort the rest.
        skipped, failures = bulk_update_external_data_job_schedules(external_data_schemas)
        for schema_id, exc in failures:
            logger.exception(
                "Error updating external data schema schedule", external_data_schema_id=schema_id, exc_info=exc
            )

        updated = len(external_data_schemas) - len(skipped) - len(failures)
        logger.info("Done!", updated=updated, skipped=len(skipped), failed=len(failures))
