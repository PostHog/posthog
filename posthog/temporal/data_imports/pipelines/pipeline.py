from dataclasses import dataclass
from typing import Literal
from uuid import UUID

import dlt
from django.conf import settings
from dlt.pipeline.exceptions import PipelineStepFailed

from asgiref.sync import async_to_sync
import asyncio
from posthog.settings.base_variables import TEST
from structlog.typing import FilteringBoundLogger
from dlt.common.libs.deltalake import get_delta_tables
from dlt.common.normalizers.naming.snake_case import NamingConvention
from dlt.load.exceptions import LoadClientJobRetry
from dlt.sources import DltSource
from deltalake.exceptions import DeltaError
from collections import Counter

from posthog.warehouse.data_load.validate_schema import validate_schema_and_update_table
from posthog.warehouse.models.external_data_job import ExternalDataJob, get_external_data_job
from posthog.warehouse.models.external_data_schema import ExternalDataSchema, aget_schema_by_id
from posthog.warehouse.models.external_data_source import ExternalDataSource
from posthog.warehouse.models.table import DataWarehouseTable
from posthog.warehouse.s3 import get_s3_client


@dataclass
class PipelineInputs:
    source_id: UUID
    run_id: str
    schema_id: UUID
    dataset_name: str
    job_type: ExternalDataSource.Type
    team_id: int


class DataImportPipeline:
    loader_file_format: Literal["parquet"] = "parquet"

    def __init__(
        self,
        inputs: PipelineInputs,
        source: DltSource,
        logger: FilteringBoundLogger,
        reset_pipeline: bool,
        incremental: bool = False,
    ):
        self.inputs = inputs
        self.logger = logger

        self._incremental = incremental
        self.refresh_dlt = reset_pipeline
        self.should_chunk_pipeline = (
            incremental
            and inputs.job_type != ExternalDataSource.Type.POSTGRES
            and inputs.job_type != ExternalDataSource.Type.MYSQL
            and inputs.job_type != ExternalDataSource.Type.MSSQL
            and inputs.job_type != ExternalDataSource.Type.SNOWFLAKE
        )

        if self.should_chunk_pipeline:
            # Incremental syncs: Assuming each page is 100 items for now so bound each run at 50_000 items
            self.source = source.add_limit(500)
        else:
            self.source = source

    def _get_pipeline_name(self):
        return f"{self.inputs.job_type}_pipeline_{self.inputs.team_id}_run_{self.inputs.schema_id}"

    def _get_destination(self):
        if TEST:
            credentials = {
                "aws_access_key_id": settings.AIRBYTE_BUCKET_KEY,
                "aws_secret_access_key": settings.AIRBYTE_BUCKET_SECRET,
                "endpoint_url": settings.OBJECT_STORAGE_ENDPOINT,
                "region_name": settings.AIRBYTE_BUCKET_REGION,
                "AWS_ALLOW_HTTP": "true",
                "AWS_S3_ALLOW_UNSAFE_RENAME": "true",
            }
        else:
            credentials = {
                "aws_access_key_id": settings.AIRBYTE_BUCKET_KEY,
                "aws_secret_access_key": settings.AIRBYTE_BUCKET_SECRET,
                "region_name": settings.AIRBYTE_BUCKET_REGION,
                "AWS_S3_ALLOW_UNSAFE_RENAME": "true",
            }

        return dlt.destinations.filesystem(
            credentials=credentials,
            bucket_url=settings.BUCKET_URL,  # type: ignore
        )

    def _create_pipeline(self):
        pipeline_name = self._get_pipeline_name()
        destination = self._get_destination()

        return dlt.pipeline(
            pipeline_name=pipeline_name,
            destination=destination,
            dataset_name=self.inputs.dataset_name,
        )

    async def _prepare_s3_files_for_querying(self, file_uris: list[str]):
        s3 = get_s3_client()
        job: ExternalDataJob = await get_external_data_job(job_id=self.inputs.run_id)
        schema: ExternalDataSchema = await aget_schema_by_id(self.inputs.schema_id, self.inputs.team_id)

        normalized_schema_name = NamingConvention().normalize_identifier(schema.name)
        s3_folder_for_job = f"{settings.BUCKET_URL}/{job.folder_path()}"
        s3_folder_for_schema = f"{s3_folder_for_job}/{normalized_schema_name}"
        s3_folder_for_querying = f"{s3_folder_for_job}/{normalized_schema_name}__query"

        if s3.exists(s3_folder_for_querying):
            s3.delete(s3_folder_for_querying, recursive=True)

        for file in file_uris:
            file_name = file.replace(f"{s3_folder_for_schema}/", "")
            s3.copy(file, f"{s3_folder_for_querying}/{file_name}")

    def _run(self) -> dict[str, int]:
        if self.refresh_dlt:
            self.logger.info("Pipeline getting a full refresh due to reset_pipeline being set")

        pipeline = self._create_pipeline()

        total_counts: Counter[str] = Counter({})

        # Do chunking for incremental syncing on API based endpoints (e.g. not sql databases)
        if self.should_chunk_pipeline:
            # will get overwritten
            counts: Counter[str] = Counter({"start": 1})
            pipeline_runs = 0

            while counts:
                self.logger.info(f"Running incremental (non-sql) pipeline, run ${pipeline_runs}")

                try:
                    pipeline.run(
                        self.source,
                        loader_file_format=self.loader_file_format,
                        refresh="drop_sources" if self.refresh_dlt and pipeline_runs == 0 else None,
                    )
                except PipelineStepFailed as e:
                    # Remove once DLT support writing empty Delta files
                    if isinstance(e.exception, LoadClientJobRetry):
                        if "Generic S3 error" not in e.exception.retry_message:
                            raise
                    elif isinstance(e.exception, DeltaError):
                        if e.exception.args[0] != "Generic error: No data source supplied to write command.":
                            raise
                    else:
                        raise

                if pipeline.last_trace.last_normalize_info is not None:
                    row_counts = pipeline.last_trace.last_normalize_info.row_counts
                else:
                    row_counts = {}
                # Remove any DLT tables from the counts
                filtered_rows = dict(filter(lambda pair: not pair[0].startswith("_dlt"), row_counts.items()))
                counts = Counter(filtered_rows)
                total_counts = counts + total_counts

                if total_counts.total() > 0:
                    delta_tables = get_delta_tables(pipeline)

                    table_format = DataWarehouseTable.TableFormat.DeltaS3Wrapper

                    # Workaround while we fix msising table_format on DLT resource
                    if len(delta_tables.values()) == 0:
                        table_format = DataWarehouseTable.TableFormat.Delta

                    # There should only ever be one table here
                    for table in delta_tables.values():
                        self.logger.info("Compacting delta table")
                        table.optimize.compact()
                        table.vacuum(retention_hours=24, enforce_retention_duration=False, dry_run=False)

                        file_uris = table.file_uris()
                        self.logger.info(f"Preparing S3 files - total parquet files: {len(file_uris)}")
                        async_to_sync(self._prepare_s3_files_for_querying)(file_uris)

                    self.logger.info(f"Table format: {table_format}")

                    async_to_sync(validate_schema_and_update_table)(
                        run_id=self.inputs.run_id,
                        team_id=self.inputs.team_id,
                        schema_id=self.inputs.schema_id,
                        table_schema=self.source.schema.tables,
                        row_count=total_counts.total(),
                        table_format=table_format,
                    )
                else:
                    self.logger.info("No table_counts, skipping validate_schema_and_update_table")

                pipeline_runs = pipeline_runs + 1
        else:
            self.logger.info("Running standard pipeline")
            try:
                pipeline.run(
                    self.source,
                    loader_file_format=self.loader_file_format,
                    refresh="drop_sources" if self.refresh_dlt else None,
                )
            except PipelineStepFailed as e:
                # Remove once DLT support writing empty Delta files
                if isinstance(e.exception, LoadClientJobRetry):
                    if "Generic S3 error" not in e.exception.retry_message:
                        raise
                elif isinstance(e.exception, DeltaError):
                    if e.exception.args[0] != "Generic error: No data source supplied to write command.":
                        raise
                else:
                    raise

            if pipeline.last_trace.last_normalize_info is not None:
                row_counts = pipeline.last_trace.last_normalize_info.row_counts
            else:
                row_counts = {}

            filtered_rows = dict(filter(lambda pair: not pair[0].startswith("_dlt"), row_counts.items()))
            counts = Counter(filtered_rows)
            total_counts = total_counts + counts

            if total_counts.total() > 0:
                delta_tables = get_delta_tables(pipeline)

                table_format = DataWarehouseTable.TableFormat.DeltaS3Wrapper

                # Workaround while we fix msising table_format on DLT resource
                if len(delta_tables.values()) == 0:
                    table_format = DataWarehouseTable.TableFormat.Delta

                # There should only ever be one table here
                for table in delta_tables.values():
                    self.logger.info("Compacting delta table")
                    table.optimize.compact()
                    table.vacuum(retention_hours=24, enforce_retention_duration=False, dry_run=False)

                    file_uris = table.file_uris()
                    self.logger.info(f"Preparing S3 files - total parquet files: {len(file_uris)}")
                    async_to_sync(self._prepare_s3_files_for_querying)(file_uris)

                self.logger.info(f"Table format: {table_format}")

                async_to_sync(validate_schema_and_update_table)(
                    run_id=self.inputs.run_id,
                    team_id=self.inputs.team_id,
                    schema_id=self.inputs.schema_id,
                    table_schema=self.source.schema.tables,
                    row_count=total_counts.total(),
                    table_format=table_format,
                )
            else:
                self.logger.info("No table_counts, skipping validate_schema_and_update_table")

        # Delete local state from the file system
        pipeline.drop()

        return dict(total_counts)

    async def run(self) -> dict[str, int]:
        try:
            return await asyncio.to_thread(self._run)
        except PipelineStepFailed as e:
            self.logger.exception(f"Data import failed for endpoint with exception {e}", exc_info=e)
            raise
