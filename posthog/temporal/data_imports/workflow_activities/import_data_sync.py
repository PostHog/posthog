import uuid
import asyncio
import dataclasses
from typing import Any, Optional

from django.db.models import Prefetch

from structlog.contextvars import bind_contextvars
from structlog.typing import FilteringBoundLogger
from temporalio import activity

from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.sync import database_sync_to_async_pool
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.logger import get_logger
from posthog.temporal.common.shutdown import ShutdownMonitor
from posthog.temporal.data_imports.pipelines.common.extract import (
    handle_non_retryable_error,
    report_heartbeat_timeout,
    trim_source_job_inputs,
)
from posthog.temporal.data_imports.pipelines.pipeline.pipeline import PipelineNonDLT, PipelineResult
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs, SourceResponse
from posthog.temporal.data_imports.pipelines.pipeline_sync import PipelineInputs
from posthog.temporal.data_imports.row_tracking import setup_row_tracking
from posthog.temporal.data_imports.sources import SourceRegistry
from posthog.temporal.data_imports.sources.common.base import ResumableSource
from posthog.temporal.data_imports.sources.common.resumable import ResumableSourceManager

from products.data_warehouse.backend.models import DataWarehouseTable, ExternalDataJob, ExternalDataSource
from products.data_warehouse.backend.models.external_data_schema import ExternalDataSchema, process_incremental_value
from products.data_warehouse.backend.types import ExternalDataSourceType

LOGGER = get_logger(__name__)


@dataclasses.dataclass
class ImportDataActivityInputs:
    team_id: int
    schema_id: uuid.UUID
    source_id: uuid.UUID
    run_id: str
    reset_pipeline: Optional[bool] = None

    @property
    def properties_to_log(self) -> dict[str, Any]:
        return {
            "team_id": self.team_id,
            "schema_id": self.schema_id,
            "source_id": self.source_id,
            "run_id": self.run_id,
            "reset_pipeline": self.reset_pipeline,
        }


@database_sync_to_async_pool
def _get_external_data_job(run_id: str) -> ExternalDataJob:
    return ExternalDataJob.objects.prefetch_related(
        "pipeline", Prefetch("schema", queryset=ExternalDataSchema.objects.prefetch_related("source"))
    ).get(id=run_id)


@database_sync_to_async_pool
def _get_external_data_schema(schema_id: uuid.UUID, team_id: int) -> ExternalDataSchema:
    return (
        ExternalDataSchema.objects.prefetch_related("source", "table")
        .exclude(deleted=True)
        .get(id=schema_id, team_id=team_id)
    )


@activity.defn
async def import_data_activity_sync(inputs: ImportDataActivityInputs) -> PipelineResult:
    bind_contextvars(team_id=inputs.team_id)
    logger = LOGGER.bind()
    tag_queries(team_id=inputs.team_id, product=Product.WAREHOUSE, feature=Feature.IMPORT_PIPELINE)

    await asyncio.to_thread(report_heartbeat_timeout, inputs, logger)

    async with Heartbeater(factor=30), ShutdownMonitor() as shutdown_monitor:
        await setup_row_tracking(inputs.team_id, inputs.schema_id)

        model = await _get_external_data_job(inputs.run_id)

        await logger.adebug("Running import_data_activity")

        source_type = ExternalDataSourceType(model.pipeline.source_type)

        job_inputs = PipelineInputs(
            source_id=inputs.source_id,
            schema_id=inputs.schema_id,
            run_id=inputs.run_id,
            team_id=inputs.team_id,
            job_type=source_type,
            dataset_name=await database_sync_to_async_pool(model.folder_path)(),
        )

        await trim_source_job_inputs(model.pipeline)

        schema: ExternalDataSchema | None = model.schema
        assert schema is not None

        if inputs.reset_pipeline is not None:
            reset_pipeline = inputs.reset_pipeline
        else:
            reset_pipeline = schema.sync_type_config.get("reset_pipeline", False) is True

        await logger.adebug(f"schema.sync_type_config = {schema.sync_type_config}")
        await logger.adebug(f"reset_pipeline = {reset_pipeline}")

        schema = await _get_external_data_schema(inputs.schema_id, inputs.team_id)

        processed_incremental_last_value = None
        processed_incremental_earliest_value = None

        if reset_pipeline is not True:
            processed_incremental_last_value = process_incremental_value(
                schema.sync_type_config.get("incremental_field_last_value"),
                schema.sync_type_config.get("incremental_field_type"),
            )
            processed_incremental_earliest_value = process_incremental_value(
                schema.incremental_field_earliest_value,
                schema.incremental_field_type,
            )

        if schema.should_use_incremental_field:
            await logger.adebug(f"Incremental last value being used is: {processed_incremental_last_value}")

        if processed_incremental_earliest_value:
            await logger.adebug(f"Incremental earliest value being used is: {processed_incremental_earliest_value}")

        if SourceRegistry.is_registered(source_type):
            source_inputs = SourceInputs(
                schema_name=schema.name,
                schema_id=str(schema.id),
                team_id=inputs.team_id,
                should_use_incremental_field=schema.should_use_incremental_field,
                incremental_field=schema.incremental_field if schema.should_use_incremental_field else None,
                incremental_field_type=schema.incremental_field_type if schema.should_use_incremental_field else None,
                db_incremental_field_last_value=processed_incremental_last_value
                if schema.should_use_incremental_field
                else None,
                db_incremental_field_earliest_value=processed_incremental_earliest_value
                if schema.should_use_incremental_field
                else None,
                logger=logger,
                job_id=inputs.run_id,
            )
            new_source = SourceRegistry.get_source(source_type)
            config = new_source.parse_config(model.pipeline.job_inputs)

            resumable_source_manager: ResumableSourceManager | None = None
            if isinstance(new_source, ResumableSource):
                resumable_source_manager = new_source.get_resumable_source_manager(source_inputs)
                source_response = await database_sync_to_async_pool(new_source.source_for_pipeline)(
                    config, resumable_source_manager, source_inputs
                )
            else:
                source_response = await database_sync_to_async_pool(new_source.source_for_pipeline)(
                    config, source_inputs
                )

            return await _run(
                job_inputs=job_inputs,
                source_response=source_response,
                logger=logger,
                reset_pipeline=reset_pipeline,
                shutdown_monitor=shutdown_monitor,
                resumable_source_manager=resumable_source_manager,
            )
        else:
            raise ValueError(f"Source type {model.pipeline.source_type} not supported")


@database_sync_to_async_pool
def _get_models(
    job_id: str,
) -> tuple[ExternalDataJob, ExternalDataSchema, ExternalDataSource, DataWarehouseTable | None]:
    job = ExternalDataJob.objects.select_related("schema", "schema__table").get(id=job_id)
    schema: ExternalDataSchema | None = job.schema
    source: ExternalDataSource | None = job.pipeline
    if schema is None:
        raise Exception("No schema attached to job")
    if source is None:
        raise Exception("No source attached to job")

    table: DataWarehouseTable | None = schema.table
    return job, schema, source, table


async def _run(
    job_inputs: PipelineInputs,
    source_response: SourceResponse,
    logger: FilteringBoundLogger,
    reset_pipeline: bool,
    shutdown_monitor: ShutdownMonitor,
    resumable_source_manager: ResumableSourceManager | None,
) -> PipelineResult:
    try:
        job, schema, source, table = await _get_models(job_inputs.run_id)
        pipeline = PipelineNonDLT(
            source_response,
            logger,
            job_inputs.run_id,
            reset_pipeline,
            shutdown_monitor,
            job,
            schema,
            source,
            table,
            resumable_source_manager,
        )
        result = await pipeline.run()
        del pipeline
        await logger.adebug("Finished running pipeline")
        return result
    except Exception as e:
        source_cls = SourceRegistry.get_source(job_inputs.job_type)
        non_retryable_errors = source_cls.get_non_retryable_errors()
        error_msg = str(e)
        is_non_retryable_error = any(
            non_retryable_error in error_msg for non_retryable_error in non_retryable_errors.keys()
        )
        if is_non_retryable_error:
            await handle_non_retryable_error(job_inputs, error_msg, logger, e)
        else:
            await logger.aexception(error_msg)
            await logger.adebug("Error encountered during import_data_activity - re-raising")
            raise
