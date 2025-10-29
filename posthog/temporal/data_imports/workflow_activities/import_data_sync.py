import uuid
import dataclasses
from typing import Any, Optional

from django.db import close_old_connections
from django.db.models import Prefetch

import posthoganalytics
from structlog.contextvars import bind_contextvars
from structlog.typing import FilteringBoundLogger
from temporalio import activity

from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.temporal.common.heartbeat_sync import HeartbeaterSync
from posthog.temporal.common.logger import get_logger
from posthog.temporal.common.shutdown import ShutdownMonitor
from posthog.temporal.data_imports.pipelines.pipeline.pipeline import PipelineNonDLT
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs, SourceResponse
from posthog.temporal.data_imports.pipelines.pipeline_sync import PipelineInputs
from posthog.temporal.data_imports.row_tracking import setup_row_tracking
from posthog.temporal.data_imports.sources import SourceRegistry
from posthog.warehouse.models import ExternalDataJob, ExternalDataSource
from posthog.warehouse.models.external_data_schema import ExternalDataSchema, process_incremental_value
from posthog.warehouse.types import ExternalDataSourceType

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


def _trim_source_job_inputs(source: ExternalDataSource) -> None:
    if not source.job_inputs:
        return

    did_update_inputs = False
    for key, value in source.job_inputs.items():
        if isinstance(value, str):
            if value.startswith(" ") or value.endswith(" "):
                source.job_inputs[key] = value.strip()
                did_update_inputs = True

    if did_update_inputs:
        source.save()


def _report_heartbeat_timeout(inputs: ImportDataActivityInputs, logger: FilteringBoundLogger) -> None:
    logger.debug("Checking for heartbeat timeout reporting...")

    try:
        info = activity.info()
        heartbeat_timeout = info.heartbeat_timeout
        current_attempt_scheduled_time = info.current_attempt_scheduled_time

        if not heartbeat_timeout:
            logger.debug(f"No heartbeat timeout set for this activity: {heartbeat_timeout}")
            return

        if not current_attempt_scheduled_time:
            logger.debug(f"No current attempt scheduled time set for this activity: {current_attempt_scheduled_time}")
            return

        if info.attempt < 2:
            logger.debug(f"First attempt of activity, no heartbeat timeout to report.")
            return

        heartbeat_details = info.heartbeat_details
        if not isinstance(heartbeat_details, tuple) or len(heartbeat_details) < 1:
            logger.debug(f"No heartbeat details found to analyze for timeout: {heartbeat_details}")
            return

        last_heartbeat = heartbeat_details[-1]
        logger.debug(f"Resuming activity after failure. Last heartbeat details: {last_heartbeat}")

        if not isinstance(last_heartbeat, dict):
            logger.debug(
                f"Last heartbeat details not in expected format (dict). Found: {type(last_heartbeat)}: {last_heartbeat}"
            )
            return

        last_heartbeat_host = last_heartbeat.get("host", None)
        last_heartbeat_timestamp = last_heartbeat.get("ts", None)

        logger.debug(f"Last heartbeat was {last_heartbeat}")

        if last_heartbeat_host is None or last_heartbeat_timestamp is None:
            logger.debug(f"Incomplete heartbeat details. No host or timestamp found.")
            return

        try:
            last_heartbeat_timestamp = float(last_heartbeat_timestamp)
        except (TypeError, ValueError):
            logger.debug(f"Last heartbeat timestamp could not be converted to float: {last_heartbeat_timestamp}")
            return

        gap_between_beats = current_attempt_scheduled_time.timestamp() - float(last_heartbeat_timestamp)
        if gap_between_beats > heartbeat_timeout.total_seconds():
            logger.debug(
                "Last heartbeat was longer ago than the heartbeat timeout allows. Likely due to a pod OOM or restart.",
                last_heartbeat_host=last_heartbeat_host,
                last_heartbeat_timestamp=last_heartbeat_timestamp,
                gap_between_beats=gap_between_beats,
                heartbeat_timeout_seconds=heartbeat_timeout.total_seconds(),
            )

            posthoganalytics.capture(
                "dwh_pod_heartbeat_timeout",
                distinct_id=None,
                properties={
                    "team_id": inputs.team_id,
                    "schema_id": str(inputs.schema_id),
                    "source_id": str(inputs.source_id),
                    "run_id": inputs.run_id,
                    "host": last_heartbeat_host,
                    "gap_between_beats": gap_between_beats,
                    "heartbeat_timeout_seconds": heartbeat_timeout.total_seconds(),
                    "task_queue": info.task_queue,
                    "workflow_id": info.workflow_id,
                    "workflow_run_id": info.workflow_run_id,
                    "workflow_type": info.workflow_type,
                    "attempt": info.attempt,
                },
            )
        else:
            logger.debug("Last heartbeat was within the heartbeat timeout window. No action needed.")
    except Exception as e:
        logger.debug(f"Error while reporting heartbeat timeout: {e}", exc_info=e)


@activity.defn
def import_data_activity_sync(inputs: ImportDataActivityInputs):
    bind_contextvars(team_id=inputs.team_id)
    logger = LOGGER.bind()
    tag_queries(team_id=inputs.team_id, product=Product.WAREHOUSE, feature=Feature.IMPORT_PIPELINE)

    _report_heartbeat_timeout(inputs, logger)

    with HeartbeaterSync(factor=30, logger=logger), ShutdownMonitor() as shutdown_monitor:
        close_old_connections()
        setup_row_tracking(inputs.team_id, inputs.schema_id)

        model = ExternalDataJob.objects.prefetch_related(
            "pipeline", Prefetch("schema", queryset=ExternalDataSchema.objects.prefetch_related("source"))
        ).get(id=inputs.run_id)

        logger.debug("Running *SYNC* import_data")

        source_type = ExternalDataSourceType(model.pipeline.source_type)

        job_inputs = PipelineInputs(
            source_id=inputs.source_id,
            schema_id=inputs.schema_id,
            run_id=inputs.run_id,
            team_id=inputs.team_id,
            job_type=source_type,
            dataset_name=model.folder_path(),
        )

        _trim_source_job_inputs(model.pipeline)

        schema: ExternalDataSchema | None = model.schema
        assert schema is not None

        if inputs.reset_pipeline is not None:
            reset_pipeline = inputs.reset_pipeline
        else:
            reset_pipeline = schema.sync_type_config.get("reset_pipeline", False) is True

        logger.debug(f"schema.sync_type_config = {schema.sync_type_config}")
        logger.debug(f"reset_pipeline = {reset_pipeline}")

        schema = (
            ExternalDataSchema.objects.prefetch_related("source")
            .exclude(deleted=True)
            .get(id=inputs.schema_id, team_id=inputs.team_id)
        )

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
            logger.debug(f"Incremental last value being used is: {processed_incremental_last_value}")

        if processed_incremental_earliest_value:
            logger.debug(f"Incremental earliest value being used is: {processed_incremental_earliest_value}")

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
            source = new_source.source_for_pipeline(config, source_inputs)

            return _run(
                job_inputs=job_inputs,
                source=source,
                logger=logger,
                reset_pipeline=reset_pipeline,
                shutdown_monitor=shutdown_monitor,
            )
        else:
            raise ValueError(f"Source type {model.pipeline.source_type} not supported")


def _run(
    job_inputs: PipelineInputs,
    source: SourceResponse,
    logger: FilteringBoundLogger,
    reset_pipeline: bool,
    shutdown_monitor: ShutdownMonitor,
):
    pipeline = PipelineNonDLT(source, logger, job_inputs.run_id, reset_pipeline, shutdown_monitor)
    pipeline.run()
    logger.debug("Finished running pipeline")
    del pipeline
