import uuid
import dataclasses
from typing import Any

import posthoganalytics
from temporalio import activity

from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.models import Team
from posthog.sync import database_sync_to_async
from posthog.temporal.data_imports.signals import get_signal_emitter

from products.data_warehouse.backend.models import ExternalDataSchema
from products.signals.backend.api import emit_signal

# Maximum number of records to emit signals for per sync
MAX_SIGNALS_PER_SYNC = 1000
# Feature flag name for controlling signal emission
EMIT_SIGNALS_FEATURE_FLAG = "emit-data-import-signals"


@dataclasses.dataclass
class EmitSignalsActivityInputs:
    team_id: int
    schema_id: uuid.UUID
    source_id: uuid.UUID
    job_id: str
    source_type: str
    schema_name: str
    # ISO timestamp of when the previous sync completed
    # Used to filter records with created_at > last_synced_at
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
    emitter = get_signal_emitter(inputs.source_type, inputs.schema_name)
    # Check if we care about this source type + schema
    if emitter is None:
        activity.logger.warning(
            f"No signal emitter registered for {inputs.source_type}/{inputs.schema_name}",
            extra=inputs.properties_to_log,
        )
        return {"status": "skipped", "reason": "no_emitter_registered", "signals_emitted": 0}
    # Check if the FF enabled to allow signals emission
    # TODO: Revert after testing
    if False and not await database_sync_to_async(_is_feature_flag_enabled, thread_sensitive=False)(inputs.team_id):
        activity.logger.warning(
            f"Feature flag {EMIT_SIGNALS_FEATURE_FLAG} not enabled for team {inputs.team_id} for emitting signals",
            extra=inputs.properties_to_log,
        )
        return {"status": "skipped", "reason": "feature_flag_disabled", "signals_emitted": 0}
    # Fetch schema and team
    schema, team = await database_sync_to_async(_fetch_schema_and_team, thread_sensitive=False)(
        inputs.schema_id, inputs.team_id
    )
    if schema is None:
        activity.logger.warning(
            f"Schema {inputs.schema_id} not found for emitting signals", extra=inputs.properties_to_log
        )
        return {"status": "error", "reason": "schema_not_found", "signals_emitted": 0}
    if schema.table is None:
        activity.logger.warning(
            f"Schema {inputs.schema_id} has no table for emitting signals", extra=inputs.properties_to_log
        )
        return {"status": "skipped", "reason": "no_table", "signals_emitted": 0}
    if team is None:
        activity.logger.warning(f"Team {inputs.team_id} not found", extra=inputs.properties_to_log)
        return {"status": "error", "reason": "team_not_found", "signals_emitted": 0}
    # Query for new records
    records = await database_sync_to_async(_query_new_records, thread_sensitive=False)(
        team=team,
        table_name=schema.table.name,
        last_synced_at=inputs.last_synced_at,
        extra=inputs.properties_to_log,
    )
    if not records:
        activity.logger.warning(
            f"No new records found for {inputs.source_type}/{inputs.schema_name} for emitting signals",
            extra=inputs.properties_to_log,
        )
        return {"status": "success", "reason": "no_new_records", "signals_emitted": 0}
    # Emit signals for each record
    signals_emitted = await _emit_signals_for_records(
        team_id=inputs.team_id,
        records=records,
        extra=inputs.properties_to_log,
        emitter=emitter,
    )
    activity.logger.info(
        f"Emitted {signals_emitted} signals for {inputs.source_type}/{inputs.schema_name}",
        extra=inputs.properties_to_log,
    )
    return {"status": "success", "signals_emitted": signals_emitted}


def _is_feature_flag_enabled(team_id: int) -> bool:
    return posthoganalytics.feature_enabled(EMIT_SIGNALS_FEATURE_FLAG, str(team_id)) is True


def _fetch_schema_and_team(schema_id: uuid.UUID, team_id: int) -> tuple[ExternalDataSchema | None, Team | None]:
    schema: ExternalDataSchema | None = None
    team: Team | None = None
    try:
        schema = ExternalDataSchema.objects.prefetch_related("table", "source").get(id=schema_id, team_id=team_id)
    except ExternalDataSchema.DoesNotExist:
        pass
    try:
        team = Team.objects.get(id=team_id)
    except Team.DoesNotExist:
        pass
    return schema, team


def _query_new_records(
    team: Team,
    table_name: str,
    last_synced_at: str | None,
    extra: dict[str, Any],
) -> list[dict[str, Any]]:
    if last_synced_at is not None:
        query = f"""
            SELECT *
            FROM {table_name}
            WHERE created_at > {{last_synced_at}}
            ORDER BY created_at DESC
            LIMIT {MAX_SIGNALS_PER_SYNC}
        """
        parsed = parse_select(query, placeholders={"last_synced_at": last_synced_at})
    else:
        # First ever sync - get most recent records
        # TODO: Look max N days before in the past instead of just getting max records
        query = f"""
            SELECT *
            FROM {table_name}
            ORDER BY created_at DESC
            LIMIT {MAX_SIGNALS_PER_SYNC}
        """
        parsed = parse_select(query)
    try:
        result = execute_hogql_query(query=parsed, team=team, query_type="EmitSignalsNewRecords")
    except Exception as e:
        activity.logger.exception(f"Error querying new records: {e}", extra=extra)
        return []

    if not result.results or not result.columns:
        return []
    return [dict(zip(result.columns, row)) for row in result.results]


async def _emit_signals_for_records(
    team_id: int,
    records: list[dict[str, Any]],
    extra: dict[str, Any],
    emitter,
) -> int:
    count = 0
    for record in records:
        try:
            output = emitter(team_id, record)
            if output is None:
                # Not enough data to emit a signal
                continue
            await emit_signal(
                team_id=team_id,
                source_product="data_imports",
                source_type=output.source_type,
                source_id=output.source_id,
                description=output.description,
                weight=output.weight,
                extra=output.extra,
            )
            count += 1
        except Exception as e:
            activity.logger.exception(f"Error emitting signal for record: {e}", extra=extra)
            continue
    return count
