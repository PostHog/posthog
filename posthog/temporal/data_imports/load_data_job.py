import re
import json
import uuid
import datetime as dt
import dataclasses
from typing import Any

from django.conf import settings
from django.db import close_old_connections

import pyarrow.parquet as pq
import posthoganalytics
from structlog.contextvars import bind_contextvars
from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.logger import get_logger
from posthog.temporal.data_imports.metrics import get_data_import_finished_metric
from posthog.temporal.data_imports.pipelines.pipeline.pipeline import _notify_revenue_analytics_that_sync_has_completed
from posthog.temporal.data_imports.pipelines.pipeline.signals import BatchReadySignal, ETCompleteSignal
from posthog.utils import get_machine_id

LOGGER = get_logger(__name__)


@dataclasses.dataclass
class LoadDataJobInputs:
    team_id: int
    source_id: str
    schema_id: str
    job_id: str
    source_type: str | None

    @property
    def properties_to_log(self) -> dict[str, Any]:
        return {
            "team_id": self.team_id,
            "source_id": self.source_id,
            "schema_id": self.schema_id,
            "job_id": self.job_id,
            "source_type": self.source_type,
        }


@dataclasses.dataclass
class LoadBatchInputs:
    team_id: int
    source_id: str
    schema_id: str
    job_id: str
    batch_path: str
    batch_number: int
    schema_path: str
    is_first_batch: bool
    primary_keys: list[str] | None
    sync_type: str  # "full_refresh", "incremental", "append"

    @property
    def properties_to_log(self) -> dict[str, Any]:
        return {
            "team_id": self.team_id,
            "batch_path": self.batch_path,
            "batch_number": self.batch_number,
            "is_first_batch": self.is_first_batch,
        }


@dataclasses.dataclass
class FinalizeDeltaTableInputs:
    team_id: int
    source_id: str
    schema_id: str
    job_id: str
    manifest_path: str
    total_rows: int

    @property
    def properties_to_log(self) -> dict[str, Any]:
        return {
            "team_id": self.team_id,
            "manifest_path": self.manifest_path,
            "total_rows": self.total_rows,
        }


@dataclasses.dataclass
class CleanupTempStorageInputs:
    temp_s3_prefix: str

    @property
    def properties_to_log(self) -> dict[str, Any]:
        return {
            "temp_s3_prefix": self.temp_s3_prefix,
        }


@dataclasses.dataclass
class CheckRecoveryStateInputs:
    job_id: str

    @property
    def properties_to_log(self) -> dict[str, Any]:
        return {"job_id": self.job_id}


@dataclasses.dataclass
class RecoveryBatch:
    batch_path: str
    batch_number: int
    row_count: int
    already_loaded: bool


@dataclasses.dataclass
class RecoveryState:
    has_manifest: bool
    manifest_path: str | None
    temp_s3_prefix: str | None
    batches: list[RecoveryBatch]
    total_rows: int
    primary_keys: list[str] | None
    sync_type: str | None
    schema_path: str | None


@activity.defn
def check_recovery_state_activity(inputs: CheckRecoveryStateInputs) -> RecoveryState:
    """Check if the job has a manifest and which batches are already loaded."""
    from posthog.temporal.data_imports.pipelines.pipeline.et_manifest import ETManifest

    from products.data_warehouse.backend.models import ExternalDataJob, ExternalDataJobBatch

    bind_contextvars(job_id=inputs.job_id)
    logger = LOGGER.bind()

    close_old_connections()

    logger.debug("Checking recovery state for job")

    job = ExternalDataJob.objects.get(id=inputs.job_id)

    if not job.manifest_path:
        logger.debug("No manifest path found, no recovery state available")
        return RecoveryState(
            has_manifest=False,
            manifest_path=None,
            temp_s3_prefix=None,
            batches=[],
            total_rows=0,
            primary_keys=None,
            sync_type=None,
            schema_path=None,
        )

    # Load manifest from S3
    logger.debug(f"Loading manifest from {job.manifest_path}")
    try:
        manifest = ETManifest.load_from_s3(job.manifest_path)
    except Exception as e:
        logger.warning(f"Failed to load manifest: {e}, no recovery possible")
        return RecoveryState(
            has_manifest=False,
            manifest_path=job.manifest_path,
            temp_s3_prefix=job.temp_s3_prefix,
            batches=[],
            total_rows=0,
            primary_keys=None,
            sync_type=None,
            schema_path=None,
        )

    # Get already-loaded batches from DB (have loaded_at timestamp)
    loaded_batch_numbers = set(
        ExternalDataJobBatch.objects.filter(job_id=inputs.job_id, loaded_at__isnull=False).values_list(
            "batch_number", flat=True
        )
    )
    logger.debug(f"Found {len(loaded_batch_numbers)} already-loaded batches")

    # Build batch list from manifest
    batches = []
    for batch_number, batch_path in enumerate(manifest.parquet_files):
        row_count = manifest.get_batch_row_count(batch_number) or 0
        batches.append(
            RecoveryBatch(
                batch_path=batch_path,
                batch_number=batch_number,
                row_count=row_count,
                already_loaded=batch_number in loaded_batch_numbers,
            )
        )

    pending_count = sum(1 for b in batches if not b.already_loaded)
    logger.debug(f"Recovery state: {len(batches)} total batches, {pending_count} pending")

    return RecoveryState(
        has_manifest=True,
        manifest_path=job.manifest_path,
        temp_s3_prefix=manifest.temp_s3_prefix,
        batches=batches,
        total_rows=manifest.total_rows,
        primary_keys=manifest.primary_keys,
        sync_type=manifest.sync_type,
        schema_path=manifest.schema_path,
    )


@activity.defn
def load_batch_to_delta_activity(inputs: LoadBatchInputs) -> dict:
    """Load a single batch from temp S3 to Delta Lake."""
    from posthog.temporal.data_imports.pipelines.pipeline.delta_table_helper import DeltaTableHelper
    from posthog.temporal.data_imports.pipelines.pipeline.utils import _evolve_pyarrow_schema

    from products.data_warehouse.backend.models import ExternalDataJob
    from products.data_warehouse.backend.s3 import get_s3_client

    bind_contextvars(team_id=inputs.team_id)
    logger = LOGGER.bind()

    close_old_connections()

    logger.debug(f"Loading batch {inputs.batch_number} from {inputs.batch_path}")

    job = ExternalDataJob.objects.prefetch_related("schema").get(id=inputs.job_id)
    schema = job.schema
    assert schema is not None

    # Read parquet from temp S3
    s3_client = get_s3_client()
    full_path = f"{settings.BUCKET_URL}/{inputs.batch_path}"

    with s3_client.open(full_path, "rb") as f:
        pa_table = pq.read_table(f)

    logger.debug(f"Read {pa_table.num_rows} rows from batch {inputs.batch_number}")

    # Initialize Delta table helper
    delta_helper = DeltaTableHelper(schema.name, job, logger)

    # Get existing delta table (if any)
    delta_table = delta_helper.get_delta_table()

    # Evolve schema to match existing delta table (if any)
    pa_table = _evolve_pyarrow_schema(pa_table, delta_table.schema() if delta_table is not None else None)

    # Write to Delta Lake using sync_type and primary_keys from manifest (passed via inputs)
    should_overwrite = inputs.is_first_batch
    delta_table = delta_helper.write_to_deltalake(
        pa_table,
        inputs.sync_type,
        should_overwrite_table=should_overwrite,
        primary_keys=inputs.primary_keys,
    )

    logger.debug(f"Batch {inputs.batch_number} written to Delta Lake")

    return {
        "rows_loaded": pa_table.num_rows,
        "batch_number": inputs.batch_number,
    }


@activity.defn
def finalize_delta_table_activity(inputs: FinalizeDeltaTableInputs) -> dict:
    """Finalize Delta table: compact, vacuum, prepare for querying, update warehouse table."""
    from posthog.temporal.data_imports.pipelines.pipeline.delta_table_helper import DeltaTableHelper
    from posthog.temporal.data_imports.pipelines.pipeline.et_manifest import ETManifest
    from posthog.temporal.data_imports.pipelines.pipeline_sync import (
        update_last_synced_at_sync,
        validate_schema_and_update_table_sync,
    )
    from posthog.temporal.data_imports.util import prepare_s3_files_for_querying

    from products.data_warehouse.backend.models import DataWarehouseTable, ExternalDataJob

    bind_contextvars(team_id=inputs.team_id)
    logger = LOGGER.bind()

    close_old_connections()

    logger.debug(f"Finalizing Delta table from manifest: {inputs.manifest_path}")

    manifest = ETManifest.load_from_s3(inputs.manifest_path)

    job = ExternalDataJob.objects.prefetch_related("schema").get(id=inputs.job_id)
    schema = job.schema
    assert schema is not None

    delta_helper = DeltaTableHelper(manifest.table_name, job, logger)
    delta_table = delta_helper.get_delta_table()

    if delta_table is None:
        logger.warning("No Delta table found during finalization")
        return {"status": "no_table"}

    logger.debug("Compacting and vacuuming Delta table")
    try:
        delta_helper.compact_table()
    except Exception as e:
        logger.exception(f"Compaction failed: {e}")

    file_uris = delta_table.file_uris()
    logger.debug(f"Preparing {len(file_uris)} files for querying")

    queryable_folder = prepare_s3_files_for_querying(
        folder_path=job.folder_path(),
        table_name=manifest.table_name,
        file_uris=file_uris,
        delete_existing=True,
        existing_queryable_folder=schema.table.queryable_folder if schema.table else None,
        logger=logger,
    )

    logger.debug("Updating last synced at timestamp")
    update_last_synced_at_sync(job_id=inputs.job_id, schema_id=inputs.schema_id, team_id=inputs.team_id)

    _notify_revenue_analytics_that_sync_has_completed(schema, logger)

    logger.debug("Validating schema and updating warehouse table")
    validate_schema_and_update_table_sync(
        run_id=inputs.job_id,
        team_id=inputs.team_id,
        schema_id=uuid.UUID(inputs.schema_id),
        table_schema_dict=manifest.hogql_schema,
        row_count=inputs.total_rows,
        queryable_folder=queryable_folder,
        table_format=DataWarehouseTable.TableFormat.DeltaS3Wrapper,
    )

    logger.debug("Delta table finalization complete")

    return {
        "status": "finalized",
        "total_rows": inputs.total_rows,
        "queryable_folder": queryable_folder,
    }


@activity.defn
def cleanup_temp_storage_activity(inputs: CleanupTempStorageInputs) -> None:
    """Delete temp files from S3 after successful load."""
    from posthog.temporal.data_imports.pipelines.pipeline.temp_storage import cleanup_temp_storage

    logger = LOGGER.bind()
    logger.debug(f"Cleaning up temp storage: {inputs.temp_s3_prefix}")

    cleanup_temp_storage(inputs.temp_s3_prefix)

    logger.debug("Temp storage cleanup complete")


@workflow.defn(name="load-data-job")
class LoadDataJobWorkflow(PostHogWorkflow):
    """Load workflow that receives signals from ET workflow and processes batches sequentially."""

    @staticmethod
    def parse_inputs(inputs: list[str]) -> LoadDataJobInputs:
        loaded = json.loads(inputs[0])
        return LoadDataJobInputs(**loaded)

    # Common non-retryable errors across all sources
    _any_source_errors: dict[str, str | None] = {
        "Could not establish session to SSH gateway": None,
        "Primary key required for incremental syncs": None,
        "The primary keys for this table are not unique": None,
        "Integration matching query does not exist": None,
    }

    def __init__(self):
        self._pending_batches: list[BatchReadySignal] = []
        self._seen_batch_numbers: set[int] = set()  # Dedup batches from signals + recovery
        self._et_complete = False
        self._manifest_path: str | None = None
        self._total_batches: int = 0
        self._total_rows: int = 0
        self._batches_processed: int = 0
        self._schema_path: str | None = None
        self._temp_s3_prefix: str | None = None
        self._update_inputs: Any = None  # For sharing with error handler

    async def _handle_non_retryable_error(self, inputs: LoadDataJobInputs, internal_error: str) -> str | None:
        """Check for non-retryable errors and disable schema if detected."""
        from posthog.temporal.data_imports.sources import SourceRegistry

        from products.data_warehouse.backend.models import ExternalDataSource
        from products.data_warehouse.backend.models.external_data_schema import update_should_sync
        from products.data_warehouse.backend.types import ExternalDataSourceType

        try:
            internal_error_normalized = re.sub(r"[\n\r\t]", " ", internal_error)

            source = ExternalDataSource.objects.get(pk=inputs.source_id)
            source_cls = SourceRegistry.get_source(ExternalDataSourceType(source.source_type))
            non_retryable_errors = source_cls.get_non_retryable_errors()

            if len(non_retryable_errors) == 0:
                non_retryable_errors = self._any_source_errors
            else:
                non_retryable_errors = {**non_retryable_errors, **self._any_source_errors}

            has_non_retryable_error = any(error in internal_error_normalized for error in non_retryable_errors.keys())

            if has_non_retryable_error:
                posthoganalytics.capture(
                    distinct_id=get_machine_id(),
                    event="schema non-retryable error",
                    properties={
                        "schemaId": inputs.schema_id,
                        "sourceId": inputs.source_id,
                        "sourceType": source.source_type,
                        "jobId": inputs.job_id,
                        "teamId": inputs.team_id,
                        "error": internal_error,
                    },
                )
                update_should_sync(schema_id=inputs.schema_id, team_id=inputs.team_id, should_sync=False)

                # Return friendly error message if available
                friendly_errors = [
                    friendly_error
                    for error, friendly_error in non_retryable_errors.items()
                    if error in internal_error_normalized
                ]
                if friendly_errors and friendly_errors[0] is not None:
                    return friendly_errors[0]
        except Exception as inner_e:
            workflow.logger.exception(f"Error while handling non-retryable error: {inner_e}")

        return None

    @workflow.signal
    async def batch_ready(self, payload: BatchReadySignal) -> None:
        """Signal handler - called by ET workflow after each batch is written to temp S3."""
        if payload.batch_number in self._seen_batch_numbers:
            return
        self._seen_batch_numbers.add(payload.batch_number)
        self._pending_batches.append(payload)
        if self._schema_path is None:
            self._schema_path = payload.schema_path

    @workflow.signal
    async def et_complete(self, payload: ETCompleteSignal) -> None:
        """Signal handler - called by ET workflow when extraction is complete."""
        self._et_complete = True
        self._manifest_path = payload.manifest_path
        self._total_batches = payload.total_batches
        self._total_rows = payload.total_rows

        # manifest_path format: temp/{team_id}/{job_id}/{run_id}/manifest.json
        if payload.manifest_path:
            self._temp_s3_prefix = "/".join(payload.manifest_path.split("/")[:-1])

    @workflow.run
    async def run(self, inputs: LoadDataJobInputs) -> dict:
        from posthog.temporal.data_imports.external_data_job import (
            CreateSourceTemplateInputs,
            UpdateExternalDataJobStatusInputs,
            create_source_templates,
            update_external_data_job_model,
        )
        from posthog.temporal.data_imports.workflow_activities.calculate_table_size import (
            CalculateTableSizeActivityInputs,
            calculate_table_size_activity,
        )
        from posthog.temporal.data_imports.workflow_activities.et_activities import (
            UpdateETTrackingInputs,
            UpdateJobBatchLoadedInputs,
            update_et_tracking_activity,
            update_job_batch_loaded_activity,
        )

        from products.data_warehouse.backend.models import ExternalDataJob

        workflow.logger.info(f"Load workflow started for job {inputs.job_id}, waiting for batches...")

        await workflow.execute_activity(
            update_et_tracking_activity,
            UpdateETTrackingInputs(job_id=inputs.job_id, l_started_at=True),
            start_to_close_timeout=dt.timedelta(minutes=1),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )

        update_inputs = UpdateExternalDataJobStatusInputs(
            job_id=inputs.job_id,
            status=ExternalDataJob.Status.COMPLETED,
            latest_error=None,
            internal_error=None,
            team_id=inputs.team_id,
            schema_id=inputs.schema_id,
            source_id=inputs.source_id,
        )

        # Check for recovery state (idempotent restart support)
        # If the job has a manifest (ET completed), load batch info from it
        # and skip any batches that were already loaded to Delta Lake
        recovery_state = await workflow.execute_activity(
            check_recovery_state_activity,
            CheckRecoveryStateInputs(job_id=inputs.job_id),
            start_to_close_timeout=dt.timedelta(minutes=2),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        any_batches_already_loaded = False

        if recovery_state.has_manifest:
            workflow.logger.info(
                f"Recovery: Found manifest with {len(recovery_state.batches)} batches, "
                f"{sum(1 for b in recovery_state.batches if b.already_loaded)} already loaded"
            )

            self._manifest_path = recovery_state.manifest_path
            self._temp_s3_prefix = recovery_state.temp_s3_prefix
            self._total_rows = recovery_state.total_rows
            self._et_complete = True

            for batch in recovery_state.batches:
                self._seen_batch_numbers.add(batch.batch_number)

                if batch.already_loaded:
                    any_batches_already_loaded = True
                    self._batches_processed += 1
                else:
                    self._pending_batches.append(
                        BatchReadySignal(
                            batch_path=batch.batch_path,
                            batch_number=batch.batch_number,
                            schema_path=recovery_state.schema_path or "",
                            row_count=batch.row_count,
                            primary_keys=recovery_state.primary_keys,
                            sync_type=recovery_state.sync_type or "full_refresh",
                        )
                    )

            self._total_batches = len(recovery_state.batches)

        try:
            is_first_batch = not any_batches_already_loaded

            while True:
                # Wait for: batch available OR (ET done AND no pending batches)
                await workflow.wait_condition(
                    lambda: len(self._pending_batches) > 0 or (self._et_complete and len(self._pending_batches) == 0)
                )

                # Exit condition: ET complete and all batches processed
                if self._et_complete and len(self._pending_batches) == 0:
                    workflow.logger.info("All batches processed, finalizing...")
                    break

                if self._pending_batches:
                    batch = self._pending_batches.pop(0)
                    workflow.logger.info(f"Processing batch {batch.batch_number}")

                    await workflow.execute_activity(
                        load_batch_to_delta_activity,
                        LoadBatchInputs(
                            team_id=inputs.team_id,
                            source_id=inputs.source_id,
                            schema_id=inputs.schema_id,
                            job_id=inputs.job_id,
                            batch_path=batch.batch_path,
                            batch_number=batch.batch_number,
                            schema_path=batch.schema_path,
                            is_first_batch=is_first_batch,
                            primary_keys=batch.primary_keys,
                            sync_type=batch.sync_type,
                        ),
                        start_to_close_timeout=dt.timedelta(hours=2),
                        heartbeat_timeout=dt.timedelta(minutes=5),
                        retry_policy=RetryPolicy(
                            initial_interval=dt.timedelta(seconds=30),
                            maximum_interval=dt.timedelta(minutes=10),
                            maximum_attempts=3,
                        ),
                    )

                    await workflow.execute_activity(
                        update_job_batch_loaded_activity,
                        UpdateJobBatchLoadedInputs(
                            job_id=inputs.job_id,
                            batch_number=batch.batch_number,
                            parquet_path=batch.batch_path,
                            row_count=batch.row_count,
                        ),
                        start_to_close_timeout=dt.timedelta(minutes=1),
                        retry_policy=RetryPolicy(maximum_attempts=2),
                    )

                    self._batches_processed += 1
                    is_first_batch = False

            if self._manifest_path:
                await workflow.execute_activity(
                    finalize_delta_table_activity,
                    FinalizeDeltaTableInputs(
                        team_id=inputs.team_id,
                        source_id=inputs.source_id,
                        schema_id=inputs.schema_id,
                        job_id=inputs.job_id,
                        manifest_path=self._manifest_path,
                        total_rows=self._total_rows,
                    ),
                    start_to_close_timeout=dt.timedelta(minutes=30),
                    retry_policy=RetryPolicy(maximum_attempts=3),
                )

            await workflow.execute_activity(
                create_source_templates,
                CreateSourceTemplateInputs(team_id=inputs.team_id, run_id=inputs.job_id),
                start_to_close_timeout=dt.timedelta(minutes=10),
                retry_policy=RetryPolicy(maximum_attempts=2),
            )

            await workflow.execute_activity(
                calculate_table_size_activity,
                CalculateTableSizeActivityInputs(
                    team_id=inputs.team_id, schema_id=inputs.schema_id, job_id=inputs.job_id
                ),
                start_to_close_timeout=dt.timedelta(minutes=10),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )

            from posthog.temporal.ducklake.ducklake_copy_data_imports_workflow import (
                DataImportsDuckLakeCopyInputs,
                DuckLakeCopyDataImportsWorkflow,
            )

            await workflow.start_child_workflow(
                DuckLakeCopyDataImportsWorkflow.run,
                DataImportsDuckLakeCopyInputs(
                    team_id=inputs.team_id,
                    job_id=inputs.job_id,
                    schema_ids=[uuid.UUID(inputs.schema_id)],
                ),
                id=f"ducklake-copy-data-imports-{inputs.job_id}",
                task_queue=settings.DUCKLAKE_TASK_QUEUE,
                parent_close_policy=workflow.ParentClosePolicy.ABANDON,
            )

            await workflow.execute_activity(
                update_et_tracking_activity,
                UpdateETTrackingInputs(
                    job_id=inputs.job_id,
                    l_finished_at=True,
                    l_rows_loaded=self._total_rows,
                ),
                start_to_close_timeout=dt.timedelta(minutes=1),
                retry_policy=RetryPolicy(maximum_attempts=2),
            )

            if self._temp_s3_prefix:
                await workflow.execute_activity(
                    cleanup_temp_storage_activity,
                    CleanupTempStorageInputs(temp_s3_prefix=self._temp_s3_prefix),
                    start_to_close_timeout=dt.timedelta(minutes=10),
                    retry_policy=RetryPolicy(maximum_attempts=2),
                )

            update_inputs.rows_synced = self._total_rows

            workflow.logger.info(f"Load workflow completed. Batches processed: {self._batches_processed}")

        except Exception as e:
            update_inputs.status = ExternalDataJob.Status.FAILED
            internal_error = str(e)
            update_inputs.internal_error = internal_error
            update_inputs.latest_error = internal_error

            # Check for non-retryable errors and disable schema
            friendly_error = await self._handle_non_retryable_error(inputs, internal_error)
            if friendly_error:
                update_inputs.latest_error = friendly_error

            raise
        finally:
            get_data_import_finished_metric(source_type=inputs.source_type, status=update_inputs.status.lower()).add(1)

            await workflow.execute_activity(
                update_external_data_job_model,
                update_inputs,
                start_to_close_timeout=dt.timedelta(minutes=1),
                retry_policy=RetryPolicy(
                    initial_interval=dt.timedelta(seconds=10),
                    maximum_interval=dt.timedelta(seconds=60),
                    maximum_attempts=0,
                    non_retryable_error_types=["NotNullViolation", "IntegrityError", "DoesNotExist"],
                ),
            )

        return {
            "batches_processed": self._batches_processed,
            "total_rows": self._total_rows,
            "status": "completed",
        }
