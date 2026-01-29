import asyncio
import dataclasses

from django.conf import settings

from structlog.contextvars import bind_contextvars
from temporalio import activity

from posthog.models import DataWarehouseTable
from posthog.sync import database_sync_to_async
from posthog.temporal.common.logger import get_logger

from products.data_warehouse.backend.models import ExternalDataSchema
from products.data_warehouse.backend.models.external_data_job import ExternalDataJob
from products.data_warehouse.backend.s3 import get_size_of_folder

LOGGER = get_logger(__name__)


@dataclasses.dataclass
class CalculateTableSizeActivityInputs:
    team_id: int
    schema_id: str
    job_id: str


@activity.defn
async def calculate_table_size_activity(inputs: CalculateTableSizeActivityInputs) -> None:
    bind_contextvars(team_id=inputs.team_id)
    logger = LOGGER.bind()

    await logger.adebug("Calculating table size in S3")

    @database_sync_to_async
    def _get_schema_and_table() -> tuple[ExternalDataSchema | None, DataWarehouseTable | None, str | None]:
        try:
            schema = ExternalDataSchema.objects.get(id=inputs.schema_id)
        except ExternalDataSchema.DoesNotExist:
            return None, None, None
        table: DataWarehouseTable | None = schema.table
        folder_name = schema.folder_path()
        return schema, table, folder_name

    schema, table, folder_name = await _get_schema_and_table()

    if schema is None:
        await logger.adebug(f"Schema doesnt exist, exiting early. Schema id = {inputs.schema_id}")
        return

    @database_sync_to_async
    def _get_job() -> ExternalDataJob | None:
        try:
            return ExternalDataJob.objects.get(id=inputs.job_id)
        except ExternalDataJob.DoesNotExist:
            return None

    job = await _get_job()

    if job is None:
        await logger.adebug(f"Job doesnt exist, exiting early. Job id = {inputs.job_id}")
        return

    if not table:
        await logger.adebug("Table doesnt exist on schema, exiting early")
        return

    existing_size = table.size_in_s3_mib or 0

    await logger.adebug(f"Existing size in MiB = {existing_size:.2f}")

    if table.queryable_folder:
        s3_folder = f"{settings.BUCKET_URL}/{folder_name}/{table.queryable_folder}"
    else:
        if table.format == DataWarehouseTable.TableFormat.DeltaS3Wrapper:
            s3_folder = f"{settings.BUCKET_URL}/{folder_name}/{schema.normalized_name}__query"
        else:
            s3_folder = f"{settings.BUCKET_URL}/{folder_name}/{schema.normalized_name}"

    total_mib = await asyncio.to_thread(get_size_of_folder, s3_folder)

    await logger.adebug(f"Total size in MiB = {total_mib:.2f}")

    table_size_delta = total_mib - existing_size
    await logger.adebug(f"Table size delta in MiB = {table_size_delta:.2f}")

    @database_sync_to_async
    def _save_results():
        job_to_update = ExternalDataJob.objects.get(id=inputs.job_id)
        job_to_update.storage_delta_mib = table_size_delta
        job_to_update.save()

        table_to_update = DataWarehouseTable.objects.get(id=table.id)
        table_to_update.size_in_s3_mib = total_mib
        table_to_update.save()

    await _save_results()

    await logger.adebug("Table model updated")
