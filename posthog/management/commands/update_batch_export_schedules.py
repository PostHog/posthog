import logging

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

import structlog

from posthog.batch_exports.service import sync_batch_export
from posthog.models import BatchExport

logger = structlog.get_logger(__name__)


class Command(BaseCommand):
    help = "Updates the Temporal schedules for batch exports to ensure they are up to date"

    def add_arguments(self, parser):
        parser.add_argument("--batch-export-id", default=None, type=str, help="Single batch export ID to update")
        parser.add_argument("--team-id", default=None, type=int, help="Team ID for which to update all batch exports")
        parser.add_argument(
            "--destination-type", default=None, type=str, help="Update all batch exports for a given destination type"
        )

    def _update_batch_export_schedule(self, batch_export: BatchExport):
        logger.info("Updating batch export schedule...", batch_export_id=str(batch_export.id))

        try:
            sync_batch_export(batch_export, created=False)
        except Exception:
            logger.exception("Error updating batch export schedule", batch_export_id=str(batch_export.id))

    def handle(self, **options):
        logger.setLevel(logging.INFO)
        batch_export_id = options["batch_export_id"]

        batch_exports: list[BatchExport] = []

        if batch_export_id:
            try:
                batch_export: BatchExport = BatchExport.objects.get(id=batch_export_id, deleted=False)
                batch_exports.append(batch_export)
            except BatchExport.DoesNotExist:
                raise CommandError("Batch export not found")
            except BatchExport.MultipleObjectsReturned:
                raise CommandError("More than one existing batch export found (this should never happen)!")
        elif options["destination_type"] or options["team_id"]:
            query_set = BatchExport.objects.filter(deleted=False)

            if options["destination_type"]:
                query_set = query_set.filter(destination__type=options["destination_type"])

            if options["team_id"]:
                query_set = query_set.filter(team_id=options["team_id"])

            batch_exports = list(query_set)
        else:
            # Do we want to allow it to run on all batch exports?
            raise CommandError("No batch export ID or destination type or team ID provided")

        if len(batch_exports) == 0:
            raise CommandError("No batch exports found")

        if not settings.TEST:
            confirm = input(f"\n\tWill update schedules for {len(batch_exports)} batch exports. Proceed? (y/n) ")
            if confirm.strip().lower() != "y":
                logger.info("Aborting")
                return

        for batch_export in batch_exports:
            self._update_batch_export_schedule(batch_export)

        logger.info("Done!")
