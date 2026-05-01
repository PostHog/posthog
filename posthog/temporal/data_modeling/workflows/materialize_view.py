import json
import datetime as dt
import dataclasses

from django.conf import settings

import temporalio.common
import temporalio.workflow
import temporalio.exceptions
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.workflow import ParentClosePolicy

from posthog.exceptions_capture import capture_exception
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.data_modeling.activities import (
    CreateDataModelingJobInputs,
    DuckgresShadowInputs,
    DuckgresShadowResult,
    FailMaterializationInputs,
    MaterializeViewInputs,
    PrepareQueryableTableInputs,
    SucceedMaterializationInputs,
    check_duckgres_shadow_enabled_activity,
    create_data_modeling_job_activity,
    fail_materialization_activity,
    materialize_view_activity,
    materialize_view_duckgres_activity,
    prepare_queryable_table_activity,
    succeed_materialization_activity,
)
from posthog.temporal.data_modeling.metrics import (
    get_clickhouse_materialization_duration_metric,
    get_duckgres_shadow_duration_metric,
    get_duckgres_shadow_finished_metric,
    get_duckgres_shadow_row_count_match_metric,
    get_duckgres_shadow_rows_materialized_metric,
    get_duckgres_shadow_storage_delta_mib_metric,
    get_duckgres_shadow_storage_mib_metric,
    get_node_duration_metric,
    get_node_finished_metric,
    get_node_rows_materialized_metric,
    get_node_storage_delta_mib_metric,
    get_node_total_storage_mib_metric,
)
from posthog.temporal.ducklake.types import DataModelingDuckLakeCopyInputs, DuckLakeCopyModelInput

from products.data_warehouse.backend.models.data_modeling_job import DataModelingJobEngine

# these indicate problems with the query or data, not transient issues
NON_RETRYABLE_ERRORS = [
    "CHQueryErrorMemoryLimitExceeded",
    "CannotCoerceColumnException",
    "InvalidNodeTypeException",
    "NodeNotFoundException",
    "EmptyHogQLResponseColumnsError",
]


@dataclasses.dataclass
class MaterializeViewWorkflowInputs:
    """Inputs for the MaterializeViewWorkflow.

    Attributes:
        team_id: The team ID that owns the node.
        dag_id: The DAG the node belongs to.
        node_id: The UUID of the Node to materialize.
    """

    team_id: int
    dag_id: str
    node_id: str
    duckgres_only: bool = False
    dangerously_execute_raw_sql: bool = False

    @property
    def properties_to_log(self) -> dict:
        return {
            "team_id": self.team_id,
            "dag_id": self.dag_id,
            "node_id": self.node_id,
        }


@dataclasses.dataclass
class MaterializeViewWorkflowResult:
    """Result from the MaterializeViewWorkflow.

    Attributes:
        job_id: The ID of the DataModelingJob created for this run.
        node_id: The ID of the node that was materialized.
        rows_materialized: The number of rows written to the delta table.
        duration_seconds: The total duration of the workflow in seconds.
    """

    job_id: str
    node_id: str
    rows_materialized: int
    duration_seconds: float


@temporalio.workflow.defn(name="data-modeling-materialize-view")
class MaterializeViewWorkflow(PostHogWorkflow):
    """Temporal workflow to materialize a single view.

    This workflow handles the complete materialization of a single view/materialized view:
    1. Creates a job record to track progress
    2. Executes the HogQL query and writes results to a delta lake table
    3. Copies the data to DuckLake (if enabled)
    4. Updates the node and job with completion status

    This workflow is designed to be called directly for ad hoc materialization of a single view
    (i.e. a user clicks 'materialize now' or something to that effect), or as a child workflow
    from the DAG orchestrator workflow
    """

    @staticmethod
    def parse_inputs(inputs: list[str]) -> MaterializeViewWorkflowInputs:
        """Parse inputs from the management command CLI."""
        loaded = json.loads(inputs[0])
        return MaterializeViewWorkflowInputs(**loaded)

    @temporalio.workflow.run
    async def run(self, inputs: MaterializeViewWorkflowInputs) -> MaterializeViewWorkflowResult:
        temporalio.workflow.logger.info("Starting MaterializeViewWorkflow", extra=inputs.properties_to_log)
        start_time = temporalio.workflow.now()
        parent_info = temporalio.workflow.info().parent
        parent_workflow_id = parent_info.workflow_id if parent_info else None
        job_id = None
        duckgres_job_id = None

        # check whether duckgres shadow is enabled before creating the job
        duckgres_enabled = await temporalio.workflow.execute_activity(
            check_duckgres_shadow_enabled_activity,
            inputs.team_id,
            start_to_close_timeout=dt.timedelta(minutes=1),
            retry_policy=temporalio.common.RetryPolicy(
                maximum_attempts=1,
            ),
        )

        duckgres_shadow_handle = None
        if duckgres_enabled or inputs.duckgres_only:
            duckgres_job_id = await temporalio.workflow.execute_activity(
                create_data_modeling_job_activity,
                CreateDataModelingJobInputs(
                    team_id=inputs.team_id,
                    node_id=inputs.node_id,
                    dag_id=inputs.dag_id,
                    engine=DataModelingJobEngine.DUCKGRES,
                    parent_workflow_id=parent_workflow_id,
                ),
                start_to_close_timeout=dt.timedelta(minutes=1),
                retry_policy=temporalio.common.RetryPolicy(
                    maximum_attempts=1,
                ),
            )
            # fire-and-forget: start duckgres shadow materialization in parallel
            duckgres_shadow_handle = temporalio.workflow.start_activity(
                materialize_view_duckgres_activity,
                DuckgresShadowInputs(
                    team_id=inputs.team_id,
                    node_id=inputs.node_id,
                    dag_id=inputs.dag_id,
                    job_id=duckgres_job_id,
                    dangerously_execute_raw_sql=inputs.dangerously_execute_raw_sql,
                ),
                start_to_close_timeout=dt.timedelta(minutes=15),
                retry_policy=temporalio.common.RetryPolicy(
                    maximum_attempts=3 if inputs.duckgres_only else 1,
                    initial_interval=dt.timedelta(seconds=10),
                    maximum_interval=dt.timedelta(minutes=5),
                ),
            )

        if not inputs.duckgres_only:
            job_id = await temporalio.workflow.execute_activity(
                create_data_modeling_job_activity,
                CreateDataModelingJobInputs(
                    team_id=inputs.team_id,
                    node_id=inputs.node_id,
                    dag_id=inputs.dag_id,
                    parent_workflow_id=parent_workflow_id,
                ),
                start_to_close_timeout=dt.timedelta(minutes=1),
                retry_policy=temporalio.common.RetryPolicy(
                    maximum_attempts=1,
                ),
            )
            try:
                materialize_result = await temporalio.workflow.execute_activity(
                    materialize_view_activity,
                    MaterializeViewInputs(
                        team_id=inputs.team_id,
                        node_id=inputs.node_id,
                        dag_id=inputs.dag_id,
                        job_id=job_id,
                    ),
                    # clickhouse timeout is 10mins so start to close is that plus a bit of margin
                    start_to_close_timeout=dt.timedelta(minutes=15),
                    heartbeat_timeout=dt.timedelta(minutes=2),
                    retry_policy=temporalio.common.RetryPolicy(
                        maximum_attempts=3,
                        initial_interval=dt.timedelta(seconds=10),
                        maximum_interval=dt.timedelta(minutes=5),
                        non_retryable_error_types=NON_RETRYABLE_ERRORS,
                    ),
                    cancellation_type=temporalio.workflow.ActivityCancellationType.TRY_CANCEL,
                )

                # prepare files for querying and create DataWarehouseTable
                storage_result = await temporalio.workflow.execute_activity(
                    prepare_queryable_table_activity,
                    PrepareQueryableTableInputs(
                        team_id=inputs.team_id,
                        job_id=job_id,
                        saved_query_id=materialize_result.saved_query_id,
                        table_uri=materialize_result.table_uri,
                        file_uris=materialize_result.file_uris,
                        row_count=materialize_result.row_count,
                    ),
                    start_to_close_timeout=dt.timedelta(minutes=5),
                    retry_policy=temporalio.common.RetryPolicy(
                        maximum_attempts=3,
                    ),
                )
                try:
                    model = DuckLakeCopyModelInput(
                        model_label=materialize_result.node_name,
                        saved_query_id=materialize_result.saved_query_id,
                        table_uri=materialize_result.table_uri,
                    )
                    ducklake_inputs = DataModelingDuckLakeCopyInputs(
                        team_id=inputs.team_id, job_id=job_id, models=[model]
                    )
                    await temporalio.workflow.start_child_workflow(
                        workflow="ducklake-copy.data-modeling",
                        arg=dataclasses.asdict(ducklake_inputs),
                        id=f"ducklake-copy-data-modeling-{inputs.team_id}-{materialize_result.saved_query_id}",
                        task_queue=settings.DUCKLAKE_TASK_QUEUE,
                        parent_close_policy=ParentClosePolicy.ABANDON,
                        retry_policy=temporalio.common.RetryPolicy(
                            maximum_attempts=1,
                            non_retryable_error_types=["NondeterminismError"],
                        ),
                    )
                except WorkflowAlreadyStartedError:
                    temporalio.workflow.logger.warning(
                        "DuckLake copy already running, skipping",
                        saved_query_id=materialize_result.saved_query_id,
                    )
                except Exception as ducklake_err:
                    temporalio.workflow.logger.warning(
                        f"DuckLake copy workflow failed: {str(ducklake_err)}",
                        extra=inputs.properties_to_log,
                    )
                    capture_exception(ducklake_err)
                # handle success
                end_time = temporalio.workflow.now()
                duration_seconds = (end_time - start_time).total_seconds()
                await temporalio.workflow.execute_activity(
                    succeed_materialization_activity,
                    SucceedMaterializationInputs(
                        team_id=inputs.team_id,
                        node_id=inputs.node_id,
                        dag_id=inputs.dag_id,
                        job_id=job_id,
                        row_count=materialize_result.row_count,
                        duration_seconds=duration_seconds,
                    ),
                    start_to_close_timeout=dt.timedelta(minutes=5),
                    retry_policy=temporalio.common.RetryPolicy(
                        maximum_attempts=3,
                    ),
                )

                # after the main workflow succeeds, collect shadow stats for comparison
                if duckgres_shadow_handle is not None:
                    await self._collect_shadow_comparison(
                        duckgres_shadow_handle,
                        materialize_result.row_count,
                        duration_seconds,
                        inputs,
                    )

                temporalio.workflow.logger.info(
                    "MaterializeViewWorkflow completed successfully",
                    extra={
                        "rows_materialized": materialize_result.row_count,
                        "duration_seconds": duration_seconds,
                        **inputs.properties_to_log,
                    },
                )

                # node-level metrics
                get_node_finished_metric("completed").add(1)
                get_node_duration_metric().record(duration_seconds)
                get_node_rows_materialized_metric().record(materialize_result.row_count)
                if storage_result.storage_delta_mib is not None and storage_result.storage_delta_mib >= 0:
                    get_node_storage_delta_mib_metric().record(storage_result.storage_delta_mib)
                if storage_result.total_storage_mib is not None:
                    get_node_total_storage_mib_metric().record(storage_result.total_storage_mib)

                return MaterializeViewWorkflowResult(
                    job_id=job_id,
                    node_id=inputs.node_id,
                    rows_materialized=materialize_result.row_count,
                    duration_seconds=duration_seconds,
                )
            except Exception as e:
                # handle failure
                cancelled = isinstance(e, temporalio.exceptions.ActivityError) and isinstance(
                    e.cause, temporalio.exceptions.CancelledError
                )
                if cancelled:
                    error_message = "Workflow was cancelled"
                elif isinstance(e, temporalio.exceptions.ActivityError):
                    error_message = str(e.cause) if e.cause else str(e)
                else:
                    capture_exception(e)
                    error_message = str(e)
                temporalio.workflow.logger.error(
                    f"MaterializeViewWorkflow failed: {error_message}",
                    extra=inputs.properties_to_log,
                )
                try:
                    await temporalio.workflow.execute_activity(
                        fail_materialization_activity,
                        FailMaterializationInputs(
                            team_id=inputs.team_id,
                            node_id=inputs.node_id,
                            dag_id=inputs.dag_id,
                            job_id=job_id,
                            error=error_message,
                            cancelled=cancelled,
                        ),
                        start_to_close_timeout=dt.timedelta(minutes=5),
                        retry_policy=temporalio.common.RetryPolicy(
                            maximum_attempts=3,
                        ),
                    )
                except Exception as fail_err:
                    temporalio.workflow.logger.error(
                        f"Failed to mark job as failed: {str(fail_err)}",
                        extra=inputs.properties_to_log,
                    )
                get_node_finished_metric("cancelled" if cancelled else "failed").add(1)
                raise

        # await the duckgres shadow activity so the parent workflow's concurrency
        # semaphore isn't released until the query finishes on duckgres
        result = None
        if duckgres_shadow_handle is not None:
            try:
                result = await duckgres_shadow_handle
            except Exception as shadow_err:
                temporalio.workflow.logger.warning(
                    f"Duckgres shadow activity failed (duckgres_only): {str(shadow_err)}",
                    extra=inputs.properties_to_log,
                )
                capture_exception(shadow_err)
        # fallback to duckgres job if no clickhouse job was run
        if job_id is None:
            if duckgres_job_id is None:
                raise temporalio.exceptions.ApplicationError("No data modeling job was created")
            job_id = duckgres_job_id
        return MaterializeViewWorkflowResult(
            job_id=job_id,
            node_id=inputs.node_id,
            rows_materialized=result.row_count if result else 0,
            duration_seconds=result.duration_seconds if result else 0,
        )

    async def _collect_shadow_comparison(
        self,
        shadow_handle: temporalio.workflow.ActivityHandle[DuckgresShadowResult],
        clickhouse_row_count: int,
        clickhouse_duration_seconds: float,
        inputs: MaterializeViewWorkflowInputs,
    ) -> None:
        """Await the duckgres shadow activity and emit comparison metrics.

        The activity itself is responsible for updating its job to a terminal state.
        This is best-effort — any failure is swallowed so it never affects the workflow result.
        """
        try:
            shadow_result: DuckgresShadowResult = await shadow_handle

            row_count_matched = clickhouse_row_count == shadow_result.row_count
            status = "completed" if shadow_result.error is None else "failed"

            # prometheus metrics
            get_duckgres_shadow_finished_metric(status).add(1)
            get_clickhouse_materialization_duration_metric().record(clickhouse_duration_seconds)
            if shadow_result.error is None:
                get_duckgres_shadow_duration_metric().record(shadow_result.duration_seconds)
                get_duckgres_shadow_rows_materialized_metric().record(shadow_result.row_count)
                get_duckgres_shadow_row_count_match_metric(row_count_matched).add(1)
                if shadow_result.file_size_bytes > 0:
                    get_duckgres_shadow_storage_mib_metric().record(shadow_result.file_size_bytes / (1024 * 1024))
                    if shadow_result.file_size_delta_bytes >= 0:
                        get_duckgres_shadow_storage_delta_mib_metric().record(
                            shadow_result.file_size_delta_bytes / (1024 * 1024)
                        )

            # structured log for detailed comparison
            temporalio.workflow.logger.info(
                "duckgres_shadow_comparison",
                extra={
                    "clickhouse_rows": clickhouse_row_count,
                    "clickhouse_duration_seconds": round(clickhouse_duration_seconds, 2),
                    "duckgres_rows": shadow_result.row_count,
                    "duckgres_duration_seconds": round(shadow_result.duration_seconds, 2),
                    "duckgres_schema": shadow_result.schema_name,
                    "duckgres_table": shadow_result.table_name,
                    "duckgres_error": shadow_result.error,
                    "row_count_match": row_count_matched,
                    **inputs.properties_to_log,
                },
            )
        except Exception as shadow_err:
            get_duckgres_shadow_finished_metric("error").add(1)
            temporalio.workflow.logger.warning(
                f"Duckgres shadow comparison failed: {str(shadow_err)}",
                extra=inputs.properties_to_log,
            )
            capture_exception(shadow_err)
