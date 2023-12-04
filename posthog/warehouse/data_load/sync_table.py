from typing import List

import structlog
from django.conf import settings
from django.db.models import Q

from posthog.warehouse.data_load.pipeline import (
    PIPELINE_TYPE_SCHEMA_DEFAULT_MAPPING,
    SourceSchema,
)
from posthog.warehouse.models import DataWarehouseCredential, DataWarehouseTable
from posthog.warehouse.models.external_data_source import ExternalDataSource

logger = structlog.get_logger(__name__)


class SchemaValidationError(Exception):
    def __init__(self):
        super().__init__(f"Schema validation failed")


# TODO: make async
def is_schema_valid(source_schemas: List[SourceSchema], external_data_source_id: str, create: bool = False) -> bool:
    resource = ExternalDataSource.objects.get(pk=external_data_source_id)
    credential, _ = DataWarehouseCredential.objects.get_or_create(
        team_id=resource.team_id,
        access_key=settings.AIRBYTE_BUCKET_KEY,
        access_secret=settings.AIRBYTE_BUCKET_SECRET,
    )

    # TODO: currently not using source_schemas
    source_schemas = PIPELINE_TYPE_SCHEMA_DEFAULT_MAPPING[resource.source_type]

    for schema_name in source_schemas:
        table_name = f"{resource.prefix or ''}{resource.source_type}_{schema_name}".lower()

        folder_path = resource.folder_path if create else resource.draft_folder_path
        url_pattern = f"https://{settings.AIRBYTE_BUCKET_DOMAIN}/dlt/{folder_path}/{schema_name.lower()}/*.parquet"

        data = {
            "credential": credential,
            "name": table_name,
            "format": "Parquet",
            "url_pattern": url_pattern,
            "team_id": resource.team_id,
        }

        if create:
            exists = (
                DataWarehouseTable.objects.filter(
                    team_id=resource.team_id, external_data_source_id=resource.id, url_pattern=url_pattern
                )
                .filter(Q(deleted=False) | Q(deleted__isnull=True))
                .exists()
            )

            if exists:
                table = DataWarehouseTable.objects.filter(Q(deleted=False) | Q(deleted__isnull=True)).get(
                    team_id=resource.team_id, external_data_source_id=resource.id, url_pattern=url_pattern
                )
            else:
                table = DataWarehouseTable.objects.create(external_data_source_id=resource.id, **data)
        else:
            table = DataWarehouseTable(**data)

        try:
            table.columns = table.get_columns()
        except Exception as e:
            logger.exception(
                f"Data Warehouse: Sync Resource failed with an unexpected exception for connection: {resource.pk}",
                exc_info=e,
            )
            raise SchemaValidationError()
        else:
            if create:
                table.save()

    return True
