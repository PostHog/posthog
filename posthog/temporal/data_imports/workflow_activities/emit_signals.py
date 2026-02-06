import uuid
import asyncio
import dataclasses
from typing import Any

from django.conf import settings

import posthoganalytics
from google.genai import types
from posthoganalytics.ai.gemini import genai
from temporalio import activity

from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.models import Team
from posthog.sync import database_sync_to_async
from posthog.temporal.data_imports.signals import SignalSourceConfig, get_signal_config
from posthog.temporal.data_imports.signals.registry import SignalEmitterOutput

from products.data_warehouse.backend.models import ExternalDataSchema
from products.signals.backend.api import emit_signal

# Maximum number of records to emit signals for per sync
# TODO: Rever to 1000 after testing
MAX_SIGNALS_PER_SYNC = 10
EMIT_SIGNALS_FEATURE_FLAG = "emit-data-import-signals"
# Concurrency limit for LLM actionability checks
LLM_CONCURRENCY_LIMIT = 10


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
    config = get_signal_config(inputs.source_type, inputs.schema_name)
    # Check if we care about this source type + schema
    if config is None:
        activity.logger.warning(
            f"No signal emitter config registered for {inputs.source_type}/{inputs.schema_name}",
            extra=inputs.properties_to_log,
        )
        return {"status": "skipped", "reason": "no_config_registered", "signals_emitted": 0}
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
        config=config,
        extra=inputs.properties_to_log,
    )
    if not records:
        activity.logger.warning(
            f"No new records found for {inputs.source_type}/{inputs.schema_name} for emitting signals",
            extra=inputs.properties_to_log,
        )
        return {"status": "success", "reason": "no_new_records", "signals_emitted": 0}
    # Build emitter outputs, filtering out records with missing data
    outputs = _build_emitter_outputs(
        team_id=inputs.team_id,
        records=records,
        emitter=config.emitter,
    )
    # Keep only actionable signals, when the prompt is defined
    if config.actionability_prompt:
        outputs = await _filter_actionable(
            outputs=outputs,
            actionability_prompt=config.actionability_prompt,
            extra=inputs.properties_to_log,
        )
    if not outputs:
        return {"status": "success", "reason": "no_actionable_records", "signals_emitted": 0}
    signals_emitted = await _emit_signals(
        team_id=inputs.team_id,
        outputs=outputs,
        extra=inputs.properties_to_log,
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
    config: SignalSourceConfig,
    extra: dict[str, Any],
) -> list[dict[str, Any]]:
    where_parts: list[str] = []
    placeholders: dict[str, Any] = {}
    # Continuous sync - need to analyze all that happened since the last one
    # TODO: Reverse to "is not None" after testing
    if last_synced_at is None:
        where_parts.append("created_at > {last_synced_at}")
        placeholders["last_synced_at"] = last_synced_at
        limit = MAX_SIGNALS_PER_SYNC
    # First ever sync - look back a limited window
    else:
        where_parts.append(f"created_at > now() - interval {config.first_sync_lookback_days} day")
        limit = config.first_sync_limit
    if config.where_clause:
        where_parts.append(config.where_clause)
    where_sql = " AND ".join(where_parts)
    query = f"""
        SELECT *
        FROM {table_name}
        WHERE {where_sql}
        ORDER BY created_at DESC
        LIMIT {limit}
    """
    parsed = parse_select(query, placeholders=placeholders) if placeholders else parse_select(query)
    try:
        result = execute_hogql_query(query=parsed, team=team, query_type="EmitSignalsNewRecords")
    except Exception as e:
        activity.logger.exception(f"Error querying new records: {e}", extra=extra)
        return []
    if not result.results or not result.columns:
        return []
    return [dict(zip(result.columns, row)) for row in result.results]


def _build_emitter_outputs(
    team_id: int,
    records: list[dict[str, Any]],
    emitter,
) -> list[SignalEmitterOutput]:
    outputs = []
    for record in records:
        output = emitter(team_id, record)
        if output is not None:
            outputs.append(output)
    return outputs


async def _check_actionability(
    output: SignalEmitterOutput,
    actionability_prompt: str,
) -> bool:
    """Check if the signal is actionable through LLM-as-a-judge call"""
    try:
        client = genai.AsyncClient(api_key=settings.GEMINI_API_KEY)
        prompt = actionability_prompt.format(description=output.description)
        response = await client.models.generate_content(
            model="models/gemini-3-flash-preview",
            contents=[prompt],
            # Limiting the output in hopes it will force LLM to give a short response
            config=types.GenerateContentConfig(max_output_tokens=128),
        )
        response_text = (response.text or "").strip().upper()
        return "NOT_ACTIONABLE" not in response_text
    except Exception:
        # If LLM call fails, allow to pass to not block the emission, as fails should not happen often
        return True


async def _filter_actionable(
    outputs: list[SignalEmitterOutput],
    actionability_prompt: str,
    extra: dict[str, Any],
) -> list[SignalEmitterOutput]:
    """Keep only actionable signals"""
    semaphore = asyncio.Semaphore(LLM_CONCURRENCY_LIMIT)

    async def _bounded_check(output: SignalEmitterOutput) -> bool:
        async with semaphore:
            return await _check_actionability(output, actionability_prompt)

    tasks: dict[int, asyncio.Task[bool]] = {}
    async with asyncio.TaskGroup() as tg:
        for i, output in enumerate(outputs):
            tasks[i] = tg.create_task(_bounded_check(output))
    actionable = []
    filtered_count = 0
    for i, output in enumerate(outputs):
        result = tasks[i].result()
        if result:
            actionable.append(output)
        elif isinstance(result, Exception):
            actionable.append(output)
        else:
            filtered_count += 1
    if filtered_count > 0:
        activity.logger.info(
            f"Filtered {filtered_count} non-actionable records out of {len(outputs)}",
            extra=extra,
        )
    return actionable


async def _emit_signals(
    team_id: int,
    outputs: list[SignalEmitterOutput],
    extra: dict[str, Any],
) -> int:
    count = 0
    for output in outputs:
        try:
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
