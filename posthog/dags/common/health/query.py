from collections.abc import Mapping
from typing import Any

import dagster

from posthog.clickhouse.client import sync_execute

_DEFAULT_HEALTH_QUERY_SETTINGS: dict[str, Any] = {
    "max_execution_time": 30,
    "max_threads": 2,
}


def _validate_clickhouse_team_query(sql: str) -> None:
    if "%(team_ids)s" not in sql:
        raise ValueError("Health ClickHouse queries must include a %(team_ids)s placeholder")
    if "%(lookback_days)s" not in sql:
        raise ValueError("Health ClickHouse queries must include a %(lookback_days)s placeholder")


def execute_clickhouse_health_team_query(
    sql: str,
    *,
    team_ids: list[int],
    lookback_days: int,
    context: dagster.OpExecutionContext,
    params: Mapping[str, Any] | None = None,
    settings: Mapping[str, Any] | None = None,
) -> list[tuple[Any, ...]]:
    if lookback_days <= 0:
        raise ValueError(f"lookback_days must be > 0, got {lookback_days}")
    if not team_ids:
        return []

    _validate_clickhouse_team_query(sql)

    query_params: dict[str, Any] = {
        "team_ids": team_ids,
        "lookback_days": lookback_days,
    }

    if params:
        reserved = {"team_ids", "lookback_days"} & set(params.keys())
        if reserved:
            raise ValueError(f"Reserved params cannot be overridden: {', '.join(sorted(reserved))}")
        query_params.update(params)

    query_settings = dict(_DEFAULT_HEALTH_QUERY_SETTINGS)
    if settings:
        query_settings.update(settings)

    context.log.info(f"Running health ClickHouse query for {len(team_ids)} teams with lookback_days={lookback_days}")
    return sync_execute(sql, query_params, settings=query_settings) or []
