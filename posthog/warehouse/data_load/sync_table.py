from posthog.warehouse.data_load.pipeline import SourceSchema, PIPELINE_TYPE_SCHEMA_DEFAULT_MAPPING

from posthog.warehouse.models.external_data_source import ExternalDataSource
from posthog.warehouse.models import DataWarehouseCredential, DataWarehouseTable
from django.conf import settings
import structlog
from typing import List

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
        table_name = f"{resource.source_type}_{schema_name.lower()}"
        url_pattern = (
            f"https://{settings.AIRBYTE_BUCKET_DOMAIN}/dlt/{resource.draft_folder_path}/{schema_name.lower()}/*.parquet"
        )

        data = {
            "credential": credential,
            "name": table_name,
            "format": "Parquet",
            "url_pattern": url_pattern,
            "team_id": resource.team_id,
        }

        if create:
            exists = DataWarehouseTable.objects.filter(
                name=table_name, team_id=resource.team_id, format="Parquet"
            ).exists()
            if exists:
                table = DataWarehouseTable.objects.get(name=table_name, team_id=resource.team_id, format="Parquet")
            else:
                table = DataWarehouseTable.objects.create(**data)
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
