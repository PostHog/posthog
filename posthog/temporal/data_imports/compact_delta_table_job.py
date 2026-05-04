import json
import dataclasses
from datetime import timedelta

from django.db import close_old_connections

from structlog.contextvars import bind_contextvars
from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.logger import get_logger
from posthog.temporal.data_imports.pipelines.pipeline.delta_table_helper import DeltaTableHelper

from products.data_warehouse.backend.models import ExternalDataSchema
from products.data_warehouse.backend.models.external_data_job import ExternalDataJob

LOGGER = get_logger(__name__)


@dataclasses.dataclass
class CompactDeltaTableWorkflowInputs:
    team_id: int
    schema_id: str

    @property
    def properties_to_log(self) -> dict[str, object]:
        return {"team_id": self.team_id, "schema_id": self.schema_id}


@activity.defn
async def compact_delta_table_activity(inputs: CompactDeltaTableWorkflowInputs) -> None:
    """Run optimize.compact + vacuum on the Delta target for one schema.

    Triggered out-of-band (admin action) to remediate fragmented tables that
    can't recover via the in-pipeline pre-write compaction — e.g. when syncs
    are failing repeatedly and never reach the start-of-run compact path.
    """
    bind_contextvars(team_id=inputs.team_id, schema_id=inputs.schema_id)
    logger = LOGGER.bind()
    close_old_connections()

    schema = await ExternalDataSchema.objects.filter(id=inputs.schema_id, team_id=inputs.team_id).afirst()
    if schema is None:
        await logger.aerror(f"Schema not found: id={inputs.schema_id} team={inputs.team_id}")
        return

    job = (
        await ExternalDataJob.objects.filter(schema_id=schema.id, team_id=inputs.team_id)
        .order_by("-created_at")
        .afirst()
    )
    if job is None:
        await logger.aerror(f"No job found for schema id={inputs.schema_id} — cannot resolve folder path")
        return

    # DeltaTableHelper normalizes the resource name internally when computing
    # the delta_table_uri, so passing the raw schema name is safe.
    helper = DeltaTableHelper(resource_name=schema.name, job=job, logger=logger)

    delta_table = await helper.get_delta_table()
    if delta_table is None:
        await logger.ainfo("No Delta table at expected path; nothing to compact")
        return

    file_uris = await helper.get_file_uris()
    await logger.ainfo(f"Pre-compact file count: {len(file_uris)}")

    await helper.compact_table()

    file_uris_after = await helper.get_file_uris()
    await logger.ainfo(f"Post-compact file count: {len(file_uris_after)}")


@workflow.defn(name="dwh-compact-delta-table")
class CompactDeltaTableWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> CompactDeltaTableWorkflowInputs:
        loaded = json.loads(inputs[0])
        return CompactDeltaTableWorkflowInputs(**loaded)

    @workflow.run
    async def run(self, inputs: CompactDeltaTableWorkflowInputs) -> None:
        await workflow.execute_activity(
            compact_delta_table_activity,
            inputs,
            start_to_close_timeout=timedelta(hours=2),
            heartbeat_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )
