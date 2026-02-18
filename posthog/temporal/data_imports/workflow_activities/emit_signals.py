import json
import uuid
import asyncio
import dataclasses
from datetime import datetime, timedelta
from typing import Any

from django.conf import settings

import posthoganalytics
from google.genai import types
from posthoganalytics.ai.gemini import AsyncClient, genai
from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.models import Team
from posthog.sync import database_sync_to_async
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.data_imports.signals import SignalEmitter, SignalSourceTableConfig, get_signal_config
from posthog.temporal.data_imports.signals.registry import SignalEmitterOutput

from products.data_warehouse.backend.models import ExternalDataSchema
from products.signals.backend.api import emit_signal

# Concurrent LLM calls limit for actionability checks
LLM_CONCURRENCY_LIMIT = 20
# Concurrent workflow spawns for signal emission
EMIT_CONCURRENCY_LIMIT = 50


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
    config = get_signal_config(inputs.source_type, inputs.schema_name)
    # Check if we care about this source type + schema
    if config is None:
        activity.logger.warning(
            f"No signal emitter config registered for {inputs.source_type}/{inputs.schema_name}",
            extra=inputs.properties_to_log,
        )
        return {"status": "skipped", "reason": "no_config_registered", "signals_emitted": 0}

    async with Heartbeater():
        # Fetch schema and team
        schema, team = await database_sync_to_async(_fetch_schema_and_team, thread_sensitive=False)(
            inputs.schema_id, inputs.team_id
        )
        if schema.table is None:
            activity.logger.warning(
                f"Schema {inputs.schema_id} has no table for emitting signals", extra=inputs.properties_to_log
            )
            return {"status": "skipped", "reason": "no_table", "signals_emitted": 0}
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
            # Actionability prompt could be a security issue, as it contains user-generated content,
            # but it should be covered by the Signals pipeline security checks
            outputs = await _filter_actionable(
                outputs=outputs,
                actionability_prompt=config.actionability_prompt,
                extra=inputs.properties_to_log,
            )
        if not outputs:
            return {"status": "success", "reason": "no_actionable_records", "signals_emitted": 0}
        signals_emitted = await _emit_signals(
            team=team,
            outputs=outputs,
            extra=inputs.properties_to_log,
        )
        activity.logger.info(
            f"Emitted {signals_emitted} signals for {inputs.source_type}/{inputs.schema_name}",
            extra=inputs.properties_to_log,
        )
        return {"status": "success", "signals_emitted": signals_emitted}


def _fetch_schema_and_team(schema_id: uuid.UUID, team_id: int) -> tuple[ExternalDataSchema, Team]:
    schema = ExternalDataSchema.objects.prefetch_related("table", "source").get(id=schema_id, team_id=team_id)
    team = Team.objects.get(id=team_id)
    return schema, team


def _query_new_records(
    team: Team,
    table_name: str,
    last_synced_at: str | None,
    config: SignalSourceTableConfig,
    extra: dict[str, Any],
) -> list[dict[str, Any]]:
    where_parts: list[str] = []
    placeholders: dict[str, Any] = {}
    # Continuous sync - need to analyze all that happened since the last one (based on the schema schedule)
    if last_synced_at is not None:
        where_parts.append(f"{config.partition_field} > {{last_synced_at}}")
        placeholders["last_synced_at"] = ast.Constant(value=datetime.fromisoformat(last_synced_at))
    # First ever sync - look back a limited window
    else:
        where_parts.append(f"{config.partition_field} > now() - interval {config.first_sync_lookback_days} day")
    if config.where_clause:
        where_parts.append(config.where_clause)
    where_sql = " AND ".join(where_parts)
    # Limiting can cause a data loss, as the missed records won't be picked in the next sync, but it's acceptable for the current use case
    # None of the data comes externally (neither limits of table name), so it's safe to use f-string interpolation
    fields_sql = ", ".join(config.fields)
    query = f"""
        SELECT {fields_sql}
        FROM {table_name}
        WHERE {where_sql}
        LIMIT {config.max_records}
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
    emitter: SignalEmitter,
) -> list[SignalEmitterOutput]:
    outputs = []
    for record in records:
        output = emitter(team_id, record)
        if output is not None:
            outputs.append(output)
    return outputs


async def _check_actionability(
    client: AsyncClient,
    output: SignalEmitterOutput,
    actionability_prompt: str,
) -> bool:
    """Check if the signal is actionable through LLM-as-a-judge call"""
    try:
        prompt = actionability_prompt.format(description=output.description)
        response = await client.models.generate_content(
            model="models/gemini-3-flash-preview",
            contents=[prompt],
            # Limiting the output in hopes it will force LLM to give a short response
            config=types.GenerateContentConfig(max_output_tokens=128),
        )
        response_text = (response.text or "").strip().upper()
        return "NOT_ACTIONABLE" not in response_text
    except Exception as e:
        # If LLM call fails, allow to pass to not block the emission, as fails should not happen often
        posthoganalytics.capture_exception(
            e,
            properties={
                "tag": "data_warehouse_signals_import",
                "error_type": "actionability_check_failed",
                "source_type": output.source_type,
                "source_id": output.source_id,
            },
        )
        return True


async def _filter_actionable(
    outputs: list[SignalEmitterOutput],
    actionability_prompt: str,
    extra: dict[str, Any],
) -> list[SignalEmitterOutput]:
    """Keep only actionable signals"""
    client = genai.AsyncClient(api_key=settings.GEMINI_API_KEY)
    semaphore = asyncio.Semaphore(LLM_CONCURRENCY_LIMIT)
    activity.heartbeat()
    checked_count = 0

    async def _bounded_check(output: SignalEmitterOutput) -> bool:
        nonlocal checked_count
        async with semaphore:
            result = await _check_actionability(client, output, actionability_prompt)
            checked_count += 1
            if checked_count % LLM_CONCURRENCY_LIMIT == 0:
                activity.heartbeat()
            return result

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
        else:
            filtered_count += 1
    if filtered_count > 0:
        activity.logger.info(
            f"Filtered {filtered_count} non-actionable records out of {len(outputs)}",
            extra=extra,
        )
    return actionable


async def _emit_signals(
    team: Team,
    outputs: list[SignalEmitterOutput],
    extra: dict[str, Any],
) -> int:
    semaphore = asyncio.Semaphore(EMIT_CONCURRENCY_LIMIT)
    activity.heartbeat()
    completed_count = 0

    async def _bounded_emit(output: SignalEmitterOutput) -> bool:
        nonlocal completed_count
        async with semaphore:
            try:
                await emit_signal(
                    team=team,
                    source_product="data_imports",
                    source_type=output.source_type,
                    source_id=output.source_id,
                    description=output.description,
                    weight=output.weight,
                    # TODO: Add limits on extra to avoid hitting Temporal limits
                    extra=output.extra,
                )
                return True
            except Exception as e:
                activity.logger.exception(f"Error emitting signal for record: {e}", extra=extra)
                return False
            finally:
                completed_count += 1
                if completed_count % EMIT_CONCURRENCY_LIMIT == 0:
                    activity.heartbeat()

    results: dict[int, asyncio.Task[bool]] = {}
    async with asyncio.TaskGroup() as tg:
        for i, output in enumerate(outputs):
            results[i] = tg.create_task(_bounded_emit(output))
    succeeded = sum(1 for task in results.values() if task.result())
    return succeeded


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
