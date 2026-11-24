import asyncio
from datetime import timedelta

from django.conf import settings

from temporalio import workflow
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow

from products.data_modeling.backend.temporal.activities.notebook_model import (
    ModelFailure,
    ModelRun,
    RetiredNotebookUpload,
    fail_notebook_model,
    prepare_notebook_model,
    publish_notebook_model,
    remove_retired_notebook_upload,
)
from products.data_modeling.backend.temporal.workflows.materialize_view import (
    MaterializeViewWorkflowInputs,
    MaterializeViewWorkflowResult,
)


@workflow.defn(name="data-modeling-retire-notebook-upload")
class RetireNotebookUploadWorkflow(PostHogWorkflow):
    inputs_cls = RetiredNotebookUpload

    @workflow.run
    async def run(self, retired: RetiredNotebookUpload) -> None:
        await workflow.sleep(timedelta(days=1))
        await workflow.execute_activity(
            remove_retired_notebook_upload, retired, start_to_close_timeout=timedelta(minutes=2)
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
            while True:
                prepared = await workflow.execute_activity(
                    prepare_notebook_model, run, start_to_close_timeout=timedelta(minutes=2), retry_policy=retry
                )
                if prepared is not None:
                    break
                if workflow.now() - started >= timedelta(hours=7):
                    raise ValueError("The notebook stayed busy for seven hours.")
                await workflow.sleep(timedelta(seconds=30))
            await workflow.execute_child_workflow(
                "notebook-run",
                {"team_id": run.team_id, "notebook_run_id": str(run.run_id), "node_ids": prepared.node_ids},
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
        if prepared.previous_generation is not None:
            await workflow.start_child_workflow(
                RetireNotebookUploadWorkflow.run,
                RetiredNotebookUpload(team_id=run.team_id, generation=prepared.previous_generation),
                id=f"retire-notebook-upload-{run.team_id}-{run.run_id}",
                parent_close_policy=workflow.ParentClosePolicy.ABANDON,
            )
        return MaterializeViewWorkflowResult(
            job_id=str(run.run_id),
            node_id=inputs.node_id,
            rows_materialized=rows,
            duration_seconds=(workflow.now() - started).total_seconds(),
        )
