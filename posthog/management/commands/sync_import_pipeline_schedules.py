from django.core.management.base import BaseCommand

from products.data_warehouse.backend.data_load.service import (
    external_data_workflow_exists,
    sync_external_data_job_workflow,
)
from products.data_warehouse.backend.models.external_data_schema import ExternalDataSchema


class Command(BaseCommand):
    help = "Sync data warehouse import pipeline temporal schedules"

    def handle(self, *args, **options):
        # Fetch all ExternalDataSchemas that are not deleted and have synced before
        schemas = ExternalDataSchema.objects.filter(deleted=False, table_id__isnull=False)

        schema_count = len(schemas)
        print(f"Total schemas to check: {schema_count}")  # noqa: T201

        for index, schema in enumerate(schemas):
            schedule_exists = external_data_workflow_exists(str(schema.id))
            if schedule_exists:
                sync_external_data_job_workflow(schema, create=False, should_sync=schema.should_sync)

            print(  # noqa: T201
                f"Processed schema {index + 1}/{schema_count} - Schema.ID: {schema.pk}. schedule_exists={schedule_exists}"
            )
