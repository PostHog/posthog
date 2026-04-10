from datetime import datetime
from typing import Any

import structlog

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.models import Team
from posthog.temporal.data_imports.signals.registry import SignalSourceTableConfig

logger = structlog.get_logger(__name__)


def data_warehouse_record_fetcher(
    team: Team,
    config: SignalSourceTableConfig,
    context: dict[str, Any],
) -> list[dict[str, Any]]:
    """Fetch records from a data warehouse table via HogQL."""
    table_name: str = context["table_name"]
    last_synced_at: str | None = context.get("last_synced_at")
    extra: dict[str, Any] = context.get("extra", {})
    where_parts: list[str] = []
    placeholders: dict[str, Any] = {}
    partition_expr = (
        f"parseDateTimeBestEffort({config.partition_field})"
        if config.partition_field_is_datetime_string
        else config.partition_field
    )
    # Continuous sync — filter records since last sync
    if last_synced_at is not None:
        where_parts.append(f"{partition_expr} > {{last_synced_at}}")
        placeholders["last_synced_at"] = ast.Constant(value=datetime.fromisoformat(last_synced_at))
    # First ever sync — look back a limited window
    else:
        where_parts.append(f"{partition_expr} > now() - interval {config.first_sync_lookback_days} day")
    if config.where_clause:
        where_parts.append(config.where_clause)
    where_sql = " AND ".join(where_parts)
    # None of the data comes externally (neither limits of table name), so it's safe to use f-string interpolation
    fields_sql = ", ".join(config.fields)
    # Limiting can cause a data loss, as the missed records won't be picked in the next sync, but it's acceptable for the current use case
    query = f"""
        SELECT {fields_sql}
        FROM {table_name}
        WHERE {where_sql}
        LIMIT {config.max_records}
    """
    logger.info(
        "Querying new records for signal emission",
        sync_type="continuous" if last_synced_at is not None else "first",
        last_synced_at=last_synced_at,
        lookback_days=config.first_sync_lookback_days if last_synced_at is None else None,
        table_name=table_name,
        where_clause=where_sql,
        max_records=config.max_records,
        signals_type="data-import-signals",
        **extra,
    )
    parsed = parse_select(query, placeholders=placeholders) if placeholders else parse_select(query)
    try:
        result = execute_hogql_query(query=parsed, team=team, query_type="EmitSignalsNewRecords")
    except Exception as e:
        logger.exception(f"Error querying new records: {e}", **extra)
        # Raising to avoid creating permanent gaps in emitted signals, in hope the activity will fix itself on the restart
        raise
    if not result.results or not result.columns:
        return []
    return [dict(zip(result.columns, row)) for row in result.results]
