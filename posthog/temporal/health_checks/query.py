from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import structlog

from posthog.clickhouse.client import sync_execute

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class HealthQuerySettings:
    max_execution_time: int = 30
    max_threads: int = 2

    def to_dict(self) -> dict[str, Any]:
        return {"max_execution_time": self.max_execution_time, "max_threads": self.max_threads}


DEFAULT_HEALTH_QUERY_SETTINGS = HealthQuerySettings()


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
) -> list[tuple[Any, ...]]:
    if lookback_days is not None and lookback_days <= 0:
        raise ValueError(f"lookback_days must be > 0, got {lookback_days}")
    if not team_ids:
        return []

    _validate_clickhouse_team_query(sql)

    query_params: dict[str, Any] = {
        "team_ids": team_ids,
    }

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

    logger.info("running health clickhouse query", team_count=len(team_ids))
    return sync_execute(sql, query_params, settings=query_settings)
