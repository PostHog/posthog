import asyncio
from datetime import timedelta

from django.conf import settings

from temporalio import workflow
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow

from products.data_modeling.backend.temporal.activities.notebook_model import (
    ModelFailure,
    ModelRun,
    fail_notebook_model,
    prepare_notebook_model,
    publish_notebook_model,
)
from products.data_modeling.backend.temporal.workflows.materialize_view import (
    MaterializeViewWorkflowInputs,
    MaterializeViewWorkflowResult,
)


@workflow.defn(name="data-modeling-materialize-notebook")
class MaterializeNotebookWorkflow(PostHogWorkflow):
    inputs_cls = MaterializeViewWorkflowInputs

    @workflow.run
    async def run(self, inputs: MaterializeViewWorkflowInputs) -> MaterializeViewWorkflowResult:
        started = workflow.now()
        parent = workflow.info().parent
        run = ModelRun(
            team_id=inputs.team_id,
            node_id=inputs.node_id,
            dag_id=inputs.dag_id,
            run_id=workflow.uuid4(),
            triggered_by_id=inputs.manually_triggered_by_id,
            parent_workflow_id=parent.workflow_id if parent else None,
        )
        retry = RetryPolicy(maximum_attempts=3)
        try:
            node_ids = await workflow.execute_activity(
                prepare_notebook_model, run, start_to_close_timeout=timedelta(minutes=2), retry_policy=retry
            )
            await workflow.execute_child_workflow(
                "notebook-run",
                {"team_id": run.team_id, "notebook_run_id": str(run.run_id), "node_ids": node_ids},
                id=f"notebook-run-{run.run_id}",
                task_queue=settings.GENERAL_PURPOSE_TASK_QUEUE,
            )
            rows = await workflow.execute_activity(
                publish_notebook_model, run, start_to_close_timeout=timedelta(minutes=30), retry_policy=retry
            )
        except (Exception, asyncio.CancelledError) as error:
            await workflow.execute_activity(
                fail_notebook_model,
                ModelFailure(run=run, error=str(error.__cause__ or error)),
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=retry,
            )
            raise
        return MaterializeViewWorkflowResult(
            job_id=str(run.run_id),
            node_id=inputs.node_id,
            rows_materialized=rows,
            duration_seconds=(workflow.now() - started).total_seconds(),
        )
