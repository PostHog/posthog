from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import structlog

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import Workload

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class HealthQuerySettings:
    max_execution_time: int = 30
    max_threads: int = 2

    def to_dict(self) -> dict[str, Any]:
        return {"max_execution_time": self.max_execution_time, "max_threads": self.max_threads}


DEFAULT_HEALTH_QUERY_SETTINGS = HealthQuerySettings()

# Split a batch of teams into smaller statements so one query never scans every team at once.
DEFAULT_HEALTH_QUERY_CHUNK_SIZE = 50


def _validate_clickhouse_team_query(sql: str) -> None:
    if "%(team_ids)s" not in sql:
        raise ValueError("Health ClickHouse queries must include a %(team_ids)s placeholder")


def execute_clickhouse_health_team_query(
    sql: str,
    *,
    team_ids: list[int],
    lookback_days: int | None = None,
    params: Mapping[str, Any] | None = None,
    settings: Mapping[str, Any] | None = None,
    chunk_size: int = DEFAULT_HEALTH_QUERY_CHUNK_SIZE,
) -> list[tuple[Any, ...]]:
    if lookback_days is not None and lookback_days <= 0:
        raise ValueError(f"lookback_days must be > 0, got {lookback_days}")
    if chunk_size <= 0:
        raise ValueError(f"chunk_size must be > 0, got {chunk_size}")
    if not team_ids:
        return []

    _validate_clickhouse_team_query(sql)

    query_params: dict[str, Any] = {}

    if lookback_days is not None:
        query_params["lookback_days"] = lookback_days

    if params:
        reserved = {"team_ids", "lookback_days"} & set(params.keys())
        if reserved:
            raise ValueError(f"Reserved params cannot be overridden: {', '.join(sorted(reserved))}")
        query_params.update(params)

    query_settings = DEFAULT_HEALTH_QUERY_SETTINGS.to_dict()
    if settings:
        query_settings.update(settings)

    logger.info("running health clickhouse query", team_count=len(team_ids), chunk_size=chunk_size)

    rows: list[tuple[Any, ...]] = []
    for start in range(0, len(team_ids), chunk_size):
        chunk = team_ids[start : start + chunk_size]
        # Workload.OFFLINE keeps this disruption-tolerant background scan off the pool that serves
        # interactive app queries. See posthog/clickhouse/client/execute.py.
        rows.extend(
            sync_execute(
                sql,
                {**query_params, "team_ids": chunk},
                settings=query_settings,
                workload=Workload.OFFLINE,
            )
        )
    return rows
