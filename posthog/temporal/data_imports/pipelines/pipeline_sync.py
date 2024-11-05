from typing import Literal
import uuid

import dlt
from django.conf import settings
from django.db.models import Prefetch
from dlt.pipeline.exceptions import PipelineStepFailed

from posthog.settings.base_variables import TEST
from structlog.typing import FilteringBoundLogger
from dlt.common.libs.deltalake import get_delta_tables
from dlt.common.normalizers.naming.snake_case import NamingConvention
from dlt.common.schema.typing import TSchemaTables
from dlt.load.exceptions import LoadClientJobRetry
from dlt.sources import DltSource
from deltalake.exceptions import DeltaError
from collections import Counter
from clickhouse_driver.errors import ServerException

from posthog.temporal.common.logger import bind_temporal_worker_logger_sync
from posthog.temporal.data_imports.pipelines.pipeline import PipelineInputs
from posthog.warehouse.data_load.validate_schema import dlt_to_hogql_type
from posthog.warehouse.models.credential import get_or_create_datawarehouse_credential
from posthog.warehouse.models.external_data_job import ExternalDataJob
from posthog.warehouse.models.external_data_schema import ExternalDataSchema
from posthog.warehouse.models.external_data_source import ExternalDataSource
from posthog.warehouse.models.table import DataWarehouseTable
from posthog.temporal.data_imports.util import prepare_s3_files_for_querying


class DataImportPipelineSync:
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
            and inputs.job_type != ExternalDataSource.Type.BIGQUERY
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

        dlt.config["normalize.parquet_normalizer.add_dlt_load_id"] = True
        dlt.config["normalize.parquet_normalizer.add_dlt_id"] = True

        return dlt.pipeline(
            pipeline_name=pipeline_name, destination=destination, dataset_name=self.inputs.dataset_name, progress="log"
        )

    def _prepare_s3_files_for_querying(self, file_uris: list[str]):
        job = ExternalDataJob.objects.prefetch_related(
            "pipeline", Prefetch("schema", queryset=ExternalDataSchema.objects.prefetch_related("source"))
        ).get(pk=self.inputs.run_id)

        schema = (
            ExternalDataSchema.objects.prefetch_related("source")
            .exclude(deleted=True)
            .get(id=self.inputs.schema_id, team_id=self.inputs.team_id)
        )

        prepare_s3_files_for_querying(job.folder_path(), schema.name, file_uris)

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
                        self._prepare_s3_files_for_querying(file_uris)

                    self.logger.info(f"Table format: {table_format}")

                    validate_schema_and_update_table_sync(
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
                    self._prepare_s3_files_for_querying(file_uris)

                self.logger.info(f"Table format: {table_format}")

                validate_schema_and_update_table_sync(
                    run_id=self.inputs.run_id,
                    team_id=self.inputs.team_id,
                    schema_id=self.inputs.schema_id,
                    table_schema=self.source.schema.tables,
                    row_count=total_counts.total(),
                    table_format=table_format,
                )
            else:
                self.logger.info("No table_counts, skipping validate_schema_and_update_table")

        # Update last_synced_at on schema
        update_last_synced_at_sync(
            job_id=self.inputs.run_id, schema_id=str(self.inputs.schema_id), team_id=self.inputs.team_id
        )

        # Cleanup: delete local state from the file system
        pipeline.drop()

        return dict(total_counts)

    def run(self) -> dict[str, int]:
        try:
            return self._run()
        except PipelineStepFailed as e:
            self.logger.exception(f"Data import failed for endpoint with exception {e}", exc_info=e)
            raise


def update_last_synced_at_sync(job_id: str, schema_id: str, team_id: int) -> None:
    job = ExternalDataJob.objects.prefetch_related(
        "pipeline", Prefetch("schema", queryset=ExternalDataSchema.objects.prefetch_related("source"))
    ).get(pk=job_id)

    schema = (
        ExternalDataSchema.objects.prefetch_related("source").exclude(deleted=True).get(id=schema_id, team_id=team_id)
    )
    schema.last_synced_at = job.created_at

    schema.save()


def validate_schema_and_update_table_sync(
    run_id: str,
    team_id: int,
    schema_id: uuid.UUID,
    table_schema: TSchemaTables,
    row_count: int,
    table_format: DataWarehouseTable.TableFormat,
) -> None:
    """

    Validates the schemas of data that has been synced by external data job.
    If the schemas are valid, it creates or updates the DataWarehouseTable model with the new url pattern.

    Arguments:
        run_id: The id of the external data job
        team_id: The id of the team
        schema_id: The schema for which the data job relates to
        table_schema: The DLT schema from the data load stage
        table_row_counts: The count of synced rows from DLT
    """

    logger = bind_temporal_worker_logger_sync(team_id=team_id)

    if row_count == 0:
        logger.warn("Skipping `validate_schema_and_update_table` due to `row_count` being 0")
        return

    job = ExternalDataJob.objects.prefetch_related(
        "pipeline", Prefetch("schema", queryset=ExternalDataSchema.objects.prefetch_related("source"))
    ).get(pk=run_id)

    credential = get_or_create_datawarehouse_credential(
        team_id=team_id,
        access_key=settings.AIRBYTE_BUCKET_KEY,
        access_secret=settings.AIRBYTE_BUCKET_SECRET,
    )

    external_data_schema = (
        ExternalDataSchema.objects.prefetch_related("source").exclude(deleted=True).get(id=schema_id, team_id=team_id)
    )

    _schema_id = external_data_schema.id
    _schema_name: str = external_data_schema.name
    incremental = external_data_schema.is_incremental

    table_name = f"{job.pipeline.prefix or ''}{job.pipeline.source_type}_{_schema_name}".lower()
    normalized_schema_name = NamingConvention().normalize_identifier(_schema_name)
    new_url_pattern = job.url_pattern_by_schema(normalized_schema_name)

    # Check
    try:
        logger.info(f"Row count for {_schema_name} ({_schema_id}) are {row_count}")

        table_params = {
            "credential": credential,
            "name": table_name,
            "format": table_format,
            "url_pattern": new_url_pattern,
            "team_id": team_id,
            "row_count": row_count,
        }

        # create or update
        table_created: DataWarehouseTable | None = ExternalDataSchema.objects.get(id=_schema_id, team_id=team_id).table
        if table_created:
            table_created.credential = table_params["credential"]
            table_created.format = table_params["format"]
            table_created.url_pattern = new_url_pattern
            if incremental:
                table_created.row_count = table_created.get_count()
            else:
                table_created.row_count = row_count
            table_created.save()

        if not table_created:
            table_created = DataWarehouseTable.objects.create(external_data_source_id=job.pipeline.id, **table_params)

        assert isinstance(table_created, DataWarehouseTable) and table_created is not None

        # Temp fix #2 for Delta tables without table_format
        try:
            table_created.get_columns()
        except Exception as e:
            if table_format == DataWarehouseTable.TableFormat.DeltaS3Wrapper:
                logger.exception("get_columns exception with DeltaS3Wrapper format - trying Delta format", exc_info=e)

                table_created.format = DataWarehouseTable.TableFormat.Delta
                table_created.get_columns()
                table_created.save()

                logger.info("Delta format worked - updating table to use Delta")
            else:
                raise

        for schema in table_schema.values():
            if schema.get("resource") == _schema_name:
                schema_columns = schema.get("columns") or {}
                raw_db_columns: dict[str, dict[str, str]] = table_created.get_columns()
                db_columns = {key: column.get("clickhouse", "") for key, column in raw_db_columns.items()}

                columns = {}
                for column_name, db_column_type in db_columns.items():
                    dlt_column = schema_columns.get(column_name)
                    if dlt_column is not None:
                        dlt_data_type = dlt_column.get("data_type")
                        hogql_type = dlt_to_hogql_type(dlt_data_type)
                    else:
                        hogql_type = dlt_to_hogql_type(None)

                    columns[column_name] = {
                        "clickhouse": db_column_type,
                        "hogql": hogql_type,
                    }
                table_created.columns = columns
                break

        table_created.save()

        # schema could have been deleted by this point
        schema_model = (
            ExternalDataSchema.objects.prefetch_related("source")
            .exclude(deleted=True)
            .get(id=_schema_id, team_id=team_id)
        )

        if schema_model:
            schema_model.table = table_created
            schema_model.save()

    except ServerException as err:
        if err.code == 636:
            logger.exception(
                f"Data Warehouse: No data for schema {_schema_name} for external data job {job.pk}",
                exc_info=err,
            )
        else:
            logger.exception(
                f"Data Warehouse: Unknown ServerException {job.pk}",
                exc_info=err,
            )
    except Exception as e:
        # TODO: handle other exceptions here
        logger.exception(
            f"Data Warehouse: Could not validate schema for external data job {job.pk}",
            exc_info=e,
        )
        raise

    previous_jobs = list(
        ExternalDataJob.objects.prefetch_related(
            "pipeline", Prefetch("schema", queryset=ExternalDataSchema.objects.prefetch_related("source"))
        )
        .filter(schema_id=_schema_id)
        .order_by("-created_at")
        .all()
    )
    if len(previous_jobs) > 1:
        for previous_job in previous_jobs[1:]:
            try:
                previous_job.delete_deprecated_data_in_bucket()
            except Exception as e:
                logger.exception(
                    f"Data Warehouse: Could not delete deprecated data source {previous_job.pk}",
                    exc_info=e,
                )
