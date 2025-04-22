import structlog
from django.core.management.base import BaseCommand, CommandError

from posthog.batch_exports.service import sync_batch_export
from posthog.models import BatchExport

logger = structlog.get_logger(__name__)


class Command(BaseCommand):
    help = "Updates the Temporal schedule for a batch export"

    def add_arguments(self, parser):
        # TODO - add a way to update all batch exports
        parser.add_argument("--batch-export-id", default=None, type=str, help="Batch export ID to update")

    def handle(self, **options):
        batch_export_id = options["batch_export_id"]
        # verbose = options["verbosity"] > 1

        if not batch_export_id:
            raise CommandError("Batch export ID is required")

        # TODO - run in a loop once we support multiple batch exports
        try:
            batch_export: BatchExport = BatchExport.objects.get(id=batch_export_id, deleted=False)
        except BatchExport.DoesNotExist:
            raise CommandError("Batch export not found")
        except BatchExport.MultipleObjectsReturned:
            raise CommandError("More than one existing batch export found (this should never happen)!")

        logger.info("Updating batch export schedule...", batch_export_id=batch_export.id)

        try:
            sync_batch_export(batch_export, created=False)
        except Exception:
            logger.exception("Error updating batch export schedule", batch_export_id=batch_export.id)

        logger.info("Batch export schedule updated")
