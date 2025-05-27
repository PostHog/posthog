import dataclasses

from django.conf import settings
from django.db import close_old_connections
from temporalio import activity

from posthog.models import DataWarehouseTable
from posthog.temporal.common.logger import bind_temporal_worker_logger_sync
from posthog.warehouse.models import ExternalDataSchema
from posthog.warehouse.s3 import get_s3_client


@dataclasses.dataclass
class CalculateTableSizeActivityInputs:
    team_id: int
    schema_id: str


@activity.defn
def calculate_table_size_activity(inputs: CalculateTableSizeActivityInputs) -> None:
    logger = bind_temporal_worker_logger_sync(team_id=inputs.team_id)
    close_old_connections()

    logger.debug("Calculating table size in S3")

    try:
        schema = ExternalDataSchema.objects.get(id=inputs.schema_id)
    except ExternalDataSchema.DoesNotExist:
        logger.debug("Schema doesnt exist, exiting early")
        return

    table: DataWarehouseTable | None = schema.table

    if not table:
        logger.debug("Table doesnt exist on schema, exiting early")
        return

    folder_name = schema.folder_path()
    s3_folder = f"{settings.BUCKET_URL}/{folder_name}/{schema.normalized_name}"

    s3 = get_s3_client()
    files = s3.find(s3_folder, detail=True)
    total_bytes = sum(f["Size"] for f in files.values() if f["type"] != "directory")
    total_mib = total_bytes / (1024 * 1024)

    logger.debug(f"Total size in MiB = {total_mib:.2f}")

    table.size_in_s3_mib = total_mib
    table.save()

    logger.debug("Table model updated")
