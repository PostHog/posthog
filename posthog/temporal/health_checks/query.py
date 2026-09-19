import time
import random
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import structlog

from posthog.clickhouse.client import sync_execute
from posthog.errors import CH_TRANSIENT_ERRORS

logger = structlog.get_logger(__name__)

# A batch that exhausts its Temporal attempts marks all of its teams failed, which can trip the
# workflow's not-processed threshold. Cluster memory pressure is short-lived, so a few seconds of
# backoff inside the activity gets past it. The whole budget stays far below the activity's
# start_to_close_timeout.
CH_RETRY_MAX_ATTEMPTS = 3
CH_RETRY_BASE_DELAY_SECONDS = 5.0


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

    for attempt in range(1, CH_RETRY_MAX_ATTEMPTS):
        try:
            return sync_execute(sql, query_params, settings=query_settings)
        except CH_TRANSIENT_ERRORS as error:
            # Jitter keeps concurrent checks from retrying in lockstep.
            ceiling = CH_RETRY_BASE_DELAY_SECONDS * (2 ** (attempt - 1))
            delay = random.uniform(ceiling / 2, ceiling)
            logger.warning(
                "retrying health clickhouse query after transient error",
                error=str(error),
                error_type=type(error).__name__,
                attempt=attempt,
                max_attempts=CH_RETRY_MAX_ATTEMPTS,
                delay=round(delay, 1),
                team_count=len(team_ids),
            )
            time.sleep(delay)

    return sync_execute(sql, query_params, settings=query_settings)
