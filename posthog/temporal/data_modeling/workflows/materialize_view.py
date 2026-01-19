import json
import datetime as dt
import dataclasses

from django.conf import settings

import temporalio.common
import temporalio.workflow
import temporalio.exceptions
from temporalio.workflow import ParentClosePolicy

from posthog.exceptions_capture import capture_exception
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.data_modeling.activities import (
    CreateDataModelingJobInputs,
    FailMaterializationInputs,
    MaterializeViewInputs,
    PrepareQueryableTableInputs,
    SucceedMaterializationInputs,
    create_data_modeling_job_activity,
    fail_materialization_activity,
    materialize_view_activity,
    prepare_queryable_table_activity,
    succeed_materialization_activity,
)
from posthog.temporal.ducklake.types import DataModelingDuckLakeCopyInputs, DuckLakeCopyModelInput

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


@temporalio.workflow.defn(name="materialize-view")
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
        job_id = await temporalio.workflow.execute_activity(
            create_data_modeling_job_activity,
            CreateDataModelingJobInputs(
                team_id=inputs.team_id,
                node_id=inputs.node_id,
                dag_id=inputs.dag_id,
            ),
            start_to_close_timeout=dt.timedelta(minutes=1),
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
            )

            # prepare files for querying and create DataWarehouseTable
            await temporalio.workflow.execute_activity(
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
                await temporalio.workflow.start_child_workflow(
                    workflow="ducklake-copy.data-modeling",
                    arg=dataclasses.asdict(
                        DataModelingDuckLakeCopyInputs(team_id=inputs.team_id, job_id=job_id, models=[model])
                    ),
                    id=f"ducklake-copy-data-modeling-{job_id}",
                    task_queue=settings.DUCKLAKE_TASK_QUEUE,
                    parent_close_policy=ParentClosePolicy.ABANDON,
                    retry_policy=temporalio.common.RetryPolicy(
                        maximum_attempts=1,
                        non_retryable_error_types=["NondeterminismError"],
                    ),
                )
            except Exception as ducklake_err:
                # ducklake failure shouldn't fail the materialization
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
            temporalio.workflow.logger.info(
                "MaterializeViewWorkflow completed successfully",
                extra={
                    "rows_materialized": materialize_result.row_count,
                    "duration_seconds": duration_seconds,
                    **inputs.properties_to_log,
                },
            )
            return MaterializeViewWorkflowResult(
                job_id=job_id,
                node_id=inputs.node_id,
                rows_materialized=materialize_result.row_count,
                duration_seconds=duration_seconds,
            )
        except Exception as e:
            # handle failure
            if isinstance(e, temporalio.exceptions.ActivityError):
                error_message = str(e.cause) if e.cause else str(e)
                temporal_error_log = f"MaterializeViewWorkflow failed with ActivityError: {error_message}"
            else:
                capture_exception(e)
                error_message = str(e)
                temporal_error_log = f"MaterializeViewWorkflow failed with unexpected error: {error_message}"
            temporalio.workflow.logger.error(temporal_error_log, extra=inputs.properties_to_log)
            try:
                await temporalio.workflow.execute_activity(
                    fail_materialization_activity,
                    FailMaterializationInputs(
                        team_id=inputs.team_id,
                        node_id=inputs.node_id,
                        dag_id=inputs.dag_id,
                        job_id=job_id,
                        error=error_message,
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
            raise
