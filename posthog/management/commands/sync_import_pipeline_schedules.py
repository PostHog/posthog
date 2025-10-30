from django.core.management.base import BaseCommand

import structlog

from posthog.warehouse.data_load.service import external_data_workflow_exists, sync_external_data_job_workflow
from posthog.warehouse.models.external_data_schema import ExternalDataSchema

logger = structlog.get_logger(__name__)


class Command(BaseCommand):
    help = "Sync data warehouse import pipeline temporal schedules"

    def handle(self, *args, **options):
        # Fetch all ExternalDataSchemas that are not deleted and have syned before
        schemas = ExternalDataSchema.objects.filter(deleted=False, table_id__isnull=False)

        schema_count = len(schemas)
        logger.info(f"Total schemas to check: {schema_count}")

        for index, schema in enumerate(schemas):
            schedule_exists = external_data_workflow_exists(str(schema.id))
            if schedule_exists:
                sync_external_data_job_workflow(schema, create=False, should_sync=schema.should_sync)

            logger.info(
                f"Processed schema {index + 1}/{schema_count} - Schema.ID: {schema.pk}. schedule_exists={schedule_exists}"
            )
