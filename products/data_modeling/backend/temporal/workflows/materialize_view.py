import json
import datetime as dt
import dataclasses

from django.conf import settings

import temporalio.common
import temporalio.workflow
import temporalio.exceptions

from posthog.exceptions_capture import capture_exception
from posthog.temporal.common.base import PostHogWorkflow

from products.data_modeling.backend.temporal.activities.materialize import (
    CopyToDuckLakeInputs,
    CreateJobInputs,
    FailMaterializationInputs,
    FinishMaterializationInputs,
    MaterializeViewInputs,
)

with temporalio.workflow.unsafe.imports_passed_through():
    from products.data_modeling.backend.temporal.activities.materialize import (
        copy_to_ducklake_activity,
        create_materialization_job_activity,
        fail_materialization_activity,
        finish_materialization_activity,
        materialize_view_activity,
    )


# Non-retryable errors - these indicate problems with the query or data, not transient issues
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
        ducklake_copy_completed: Whether the DuckLake copy was successful.
    """

    job_id: str
    node_id: str
    rows_materialized: int
    duration_seconds: float
    ducklake_copy_completed: bool


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
        temporalio.workflow.logger.info("Starting MaterializeViewWorkflow", **inputs.properties_to_log)

        start_time = temporalio.workflow.now()

        # Step 1: Create job record
        job_id = await temporalio.workflow.execute_activity(
            create_materialization_job_activity,
            CreateJobInputs(
                team_id=inputs.team_id,
                node_id=inputs.node_id,
                dag_id=inputs.dag_id,
            ),
            start_to_close_timeout=dt.timedelta(minutes=5),
            retry_policy=temporalio.common.RetryPolicy(
                maximum_attempts=3,
                non_retryable_error_types=NON_RETRYABLE_ERRORS,
            ),
        )

        try:
            # Step 2: Materialize the view
            materialize_result = await temporalio.workflow.execute_activity(
                materialize_view_activity,
                MaterializeViewInputs(
                    team_id=inputs.team_id,
                    node_id=inputs.node_id,
                    dag_id=inputs.dag_id,
                    job_id=job_id,
                ),
                start_to_close_timeout=dt.timedelta(hours=1),
                heartbeat_timeout=dt.timedelta(minutes=2),
                retry_policy=temporalio.common.RetryPolicy(
                    maximum_attempts=3,
                    initial_interval=dt.timedelta(seconds=10),
                    maximum_interval=dt.timedelta(minutes=5),
                    non_retryable_error_types=NON_RETRYABLE_ERRORS,
                ),
            )

            # Step 3: Copy to DuckLake (if enabled)
            ducklake_completed = False
            if settings.DUCKLAKE_DATA_MODELING_COPY_WORKFLOW_ENABLED and materialize_result.file_uris:
                try:
                    ducklake_completed = await temporalio.workflow.execute_activity(
                        copy_to_ducklake_activity,
                        CopyToDuckLakeInputs(
                            team_id=inputs.team_id,
                            job_id=job_id,
                            node_id=inputs.node_id,
                            saved_query_id=materialize_result.saved_query_id,
                            table_uri=materialize_result.table_uri,
                            file_uris=materialize_result.file_uris,
                        ),
                        start_to_close_timeout=dt.timedelta(minutes=30),
                        heartbeat_timeout=dt.timedelta(minutes=2),
                        retry_policy=temporalio.common.RetryPolicy(
                            maximum_attempts=2,
                        ),
                    )
                except Exception as ducklake_err:
                    # DuckLake copy failure should not fail the workflow
                    temporalio.workflow.logger.warning(
                        f"DuckLake copy failed but continuing: {str(ducklake_err)}",
                        **inputs.properties_to_log,
                    )
                    capture_exception(ducklake_err)

            # Step 4: Mark as complete
            end_time = temporalio.workflow.now()
            duration_seconds = (end_time - start_time).total_seconds()

            await temporalio.workflow.execute_activity(
                finish_materialization_activity,
                FinishMaterializationInputs(
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
                rows=materialize_result.row_count,
                duration_seconds=duration_seconds,
                ducklake_completed=ducklake_completed,
                **inputs.properties_to_log,
            )

            return MaterializeViewWorkflowResult(
                job_id=job_id,
                node_id=inputs.node_id,
                rows_materialized=materialize_result.row_count,
                duration_seconds=duration_seconds,
                ducklake_copy_completed=ducklake_completed,
            )

        except temporalio.exceptions.ActivityError as e:
            # Handle activity failures
            error_message = str(e.cause) if e.cause else str(e)
            temporalio.workflow.logger.error(
                f"MaterializeViewWorkflow failed: {error_message}",
                **inputs.properties_to_log,
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
                    ),
                    start_to_close_timeout=dt.timedelta(minutes=5),
                    retry_policy=temporalio.common.RetryPolicy(
                        maximum_attempts=3,
                    ),
                )
            except Exception as fail_err:
                temporalio.workflow.logger.error(
                    f"Failed to mark job as failed: {str(fail_err)}",
                    **inputs.properties_to_log,
                )

            raise

        except Exception as e:
            # Handle unexpected errors
            error_message = str(e)
            temporalio.workflow.logger.error(
                f"MaterializeViewWorkflow failed with unexpected error: {error_message}",
                **inputs.properties_to_log,
            )
            capture_exception(e)

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
                    **inputs.properties_to_log,
                )

            raise
