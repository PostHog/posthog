import dataclasses
import datetime as dt
import json

from temporalio import activity, workflow
from temporalio.common import RetryPolicy
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.logger import bind_temporal_worker_logger_sync
from posthog.temporal.data_imports.pipelines.pipeline.delta_table_helper import DeltaTableHelper
from posthog.warehouse.models import ExternalDataJob, ExternalDataSchema


@dataclasses.dataclass
class DeltalakeCompactionJobWorkflowInputs:
    team_id: int
    external_data_job_id: str


@activity.defn
def run_compaction(inputs: DeltalakeCompactionJobWorkflowInputs):
    logger = bind_temporal_worker_logger_sync(team_id=inputs.team_id)
    job = ExternalDataJob.objects.get(id=inputs.external_data_job_id, team_id=inputs.team_id)

    assert job.schema is not None
    schema: ExternalDataSchema = job.schema

    delta_table_helper = DeltaTableHelper(resource_name=schema.name, job=job, logger=logger)

    delta_table_helper.compact_table()


@workflow.defn(name="deltalake-compaction-job")
class DeltalakeCompactionJobWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> DeltalakeCompactionJobWorkflowInputs:
        loaded = json.loads(inputs[0])
        return DeltalakeCompactionJobWorkflowInputs(**loaded)

    @workflow.run
    async def run(self, inputs: DeltalakeCompactionJobWorkflowInputs):
        await workflow.execute_activity(
            run_compaction,
            inputs,
            start_to_close_timeout=dt.timedelta(minutes=5),
            retry_policy=RetryPolicy(
                maximum_attempts=1,
            ),
        )
