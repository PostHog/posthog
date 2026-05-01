import json
import uuid
import dataclasses
from datetime import timedelta
from typing import Any

import structlog
from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.models import Team
from posthog.sync import database_sync_to_async
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.heartbeat import LivenessHeartbeater as Heartbeater
from posthog.temporal.data_imports.signals import get_signal_config
from posthog.temporal.data_imports.signals.pipeline import run_signal_pipeline

from products.data_warehouse.backend.models import ExternalDataSchema

logger = structlog.get_logger(__name__)


@dataclasses.dataclass(frozen=True)
class EmitSignalsActivityInputs:
    team_id: int
    schema_id: uuid.UUID
    source_id: uuid.UUID
    job_id: str
    source_type: str
    schema_name: str
    # ISO timestamp of when the previous sync completed
    # Used to filter records with partition_field > last_synced_at
    last_synced_at: str | None

    @property
    def properties_to_log(self) -> dict[str, Any]:
        return {
            "team_id": self.team_id,
            "schema_id": self.schema_id,
            "source_id": self.source_id,
            "job_id": self.job_id,
            "source_type": self.source_type,
            "schema_name": self.schema_name,
        }


@activity.defn
async def emit_data_import_signals_activity(inputs: EmitSignalsActivityInputs) -> dict[str, Any]:
    """Emit signals for newly imported records from external data sources."""
    log = logger.bind(signals_type="data-import-signals", **inputs.properties_to_log)
    log.info(f"Starting signal emission for {inputs.source_type}/{inputs.schema_name}")
    config = get_signal_config(inputs.source_type, inputs.schema_name)
    # Check if we care about this source type + schema
    if config is None:
        log.warning(f"No signal emitter config registered for {inputs.source_type}/{inputs.schema_name}")
        return {"status": "skipped", "reason": "no_config_registered", "signals_emitted": 0}
    async with Heartbeater():
        # Fetch schema and team
        schema, team = await _fetch_schema_and_team(inputs.schema_id, inputs.team_id)
        if schema.table is None:
            log.warning(f"Schema {inputs.schema_id} has no table for emitting signals")
            return {"status": "skipped", "reason": "no_table", "signals_emitted": 0}
        # Build fetcher context with data-warehouse-specific runtime values
        fetcher_context = {
            "table_name": schema.table.name,
            "last_synced_at": inputs.last_synced_at,
            "extra": inputs.properties_to_log,
        }
        records = await database_sync_to_async(config.record_fetcher, thread_sensitive=False)(
            team, config, fetcher_context
        )
        return await run_signal_pipeline(
            team=team,
            config=config,
            records=records,
            extra=inputs.properties_to_log,
        )


async def _fetch_schema_and_team(schema_id: uuid.UUID, team_id: int) -> tuple[ExternalDataSchema, Team]:
    schema = await ExternalDataSchema.objects.prefetch_related("table", "source").aget(id=schema_id, team_id=team_id)
    team = await Team.objects.aget(id=team_id)
    return schema, team


@workflow.defn(name="emit-data-import-signals")
class EmitDataImportSignalsWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> EmitSignalsActivityInputs:
        loaded = json.loads(inputs[0])
        return EmitSignalsActivityInputs(**loaded)

    @workflow.run
    async def run(self, inputs: EmitSignalsActivityInputs) -> None:
        await workflow.execute_activity(
            emit_data_import_signals_activity,
            inputs,
            start_to_close_timeout=timedelta(minutes=60),
            heartbeat_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
