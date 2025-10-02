import json
import typing
import asyncio
import datetime as dt
import dataclasses

from django.db import close_old_connections

from structlog.contextvars import bind_contextvars
from structlog.types import FilteringBoundLogger
from temporalio import activity, workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.constants import DATA_WAREHOUSE_COMPACTION_TASK_QUEUE
from posthog.exceptions_capture import capture_exception
from posthog.settings import DEBUG, TEST
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.client import sync_connect
from posthog.temporal.common.heartbeat_sync import HeartbeaterSync
from posthog.temporal.common.logger import get_logger
from posthog.temporal.data_imports.delta.base import DeltaBase
from posthog.temporal.data_imports.pipelines.pipeline.delta_table_helper import DeltaTableHelper
from posthog.temporal.hogql_query_snapshots.delta_snapshot import DeltaSnapshot
from posthog.warehouse.models import ExternalDataJob, ExternalDataSchema
from posthog.warehouse.models.datawarehouse_saved_query import DataWarehouseSavedQuery

LOGGER = get_logger(__name__)


@dataclasses.dataclass
class DeltalakeCompactionJobWorkflowInputs:
    team_id: int
    external_data_job_id: str | None = None
    saved_query_id: str | None = None

    @property
    def properties_to_log(self) -> dict[str, typing.Any]:
        return {
            "team_id": self.team_id,
            "external_data_job_id": self.external_data_job_id,
            "saved_query_id": self.saved_query_id,
        }


def trigger_compaction_snapshot(saved_query: DataWarehouseSavedQuery, logger: FilteringBoundLogger) -> str:
    name = f"{saved_query.id}"
    inputs = DeltalakeCompactionJobWorkflowInputs(team_id=saved_query.team_id, saved_query_id=saved_query.id)
    return _trigger_compaction(name, logger, inputs)


def trigger_compaction_job(job: ExternalDataJob, schema: ExternalDataSchema, logger: FilteringBoundLogger) -> str:
    name = f"{schema.id}"
    inputs = DeltalakeCompactionJobWorkflowInputs(team_id=job.team_id, external_data_job_id=job.id)
    return _trigger_compaction(name, logger, inputs)


def _trigger_compaction(name: str, logger: FilteringBoundLogger, inputs: DeltalakeCompactionJobWorkflowInputs):
    temporal = sync_connect()
    workflow_id = f"{name}-compaction"

    try:
        handle = asyncio.run(
            temporal.start_workflow(
                workflow="deltalake-compaction-job",
                arg=dataclasses.asdict(inputs),
                id=workflow_id,
                task_queue=str(DATA_WAREHOUSE_COMPACTION_TASK_QUEUE),
                retry_policy=RetryPolicy(
                    maximum_attempts=1,
                    non_retryable_error_types=["NondeterminismError"],
                ),
            )
        )

        if not DEBUG and not TEST:
            # Wait for the compaction to complete before continuing
            try:
                asyncio.run(handle.result())
            except Exception as e:
                capture_exception(e)
                logger.exception(f"Compaction job failed with: {e}", exc_info=e)
    except WorkflowAlreadyStartedError:
        pass

    return workflow_id


@activity.defn
def run_compaction(inputs: DeltalakeCompactionJobWorkflowInputs):
    bind_contextvars(team_id=inputs.team_id)
    logger = LOGGER.bind()

    with HeartbeaterSync(factor=30, logger=logger):
        close_old_connections()

        delta_table: DeltaBase | None = None

        if inputs.external_data_job_id:
            job = ExternalDataJob.objects.get(id=inputs.external_data_job_id, team_id=inputs.team_id)

            assert job.schema is not None
            schema: ExternalDataSchema = job.schema

            delta_table = DeltaTableHelper(resource_name=schema.name, job=job, logger=logger)

        if inputs.saved_query_id:
            saved_query = DataWarehouseSavedQuery.objects.get(id=inputs.saved_query_id, team_id=inputs.team_id)
            delta_table = DeltaSnapshot(saved_query)

        if delta_table is None:
            raise Exception("No delta table found")

        delta_table.compact_table()


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
            start_to_close_timeout=dt.timedelta(minutes=60),
            retry_policy=RetryPolicy(
                maximum_attempts=1,
            ),
        )
