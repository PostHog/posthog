from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Literal

import dagster

from posthog.dags.common.health.query import execute_clickhouse_health_team_query
from posthog.dags.common.health.types import BatchDetectFn, HealthCheckResult, TeamDetectFn

DetectorKind = Literal["default", "clickhouse_batch"]
ClickhouseRowMapper = Callable[[tuple[Any, ...]], tuple[int, HealthCheckResult] | None]


@dataclass(frozen=True)
class HealthDetector:
    detect_fn: BatchDetectFn | TeamDetectFn
    per_team: bool = False
    kind: DetectorKind = "default"


@dataclass(frozen=True)
class HealthExecutionPolicy:
    batch_size: int
    max_concurrent: int


_DEFAULT_POLICY_BY_KIND: dict[DetectorKind, HealthExecutionPolicy] = {
    "default": HealthExecutionPolicy(batch_size=1000, max_concurrent=5),
    "clickhouse_batch": HealthExecutionPolicy(batch_size=250, max_concurrent=1),
}


def batch_detector(detect_fn: BatchDetectFn) -> HealthDetector:
    return HealthDetector(detect_fn=detect_fn, per_team=False, kind="default")


def per_team_detector(detect_fn: TeamDetectFn) -> HealthDetector:
    return HealthDetector(detect_fn=detect_fn, per_team=True, kind="default")


def clickhouse_batch_detector(
    *,
    sql: str,
    row_mapper: ClickhouseRowMapper,
    lookback_days: int,
    params: Mapping[str, Any] | None = None,
    settings: Mapping[str, Any] | None = None,
) -> HealthDetector:
    def detect_fn(team_ids: list[int], context: dagster.OpExecutionContext) -> dict[int, list[HealthCheckResult]]:
        rows = execute_clickhouse_health_team_query(
            sql,
            team_ids=team_ids,
            lookback_days=lookback_days,
            context=context,
            params=params,
            settings=settings,
        )
        issues_by_team: dict[int, list[HealthCheckResult]] = {}
        for row in rows:
            mapped = row_mapper(row)
            if mapped is None:
                continue
            team_id, result = mapped
            issues_by_team.setdefault(team_id, []).append(result)
        return issues_by_team

    return HealthDetector(detect_fn=detect_fn, per_team=False, kind="clickhouse_batch")


def clickhouse_batch_detector_from_fn(detect_fn: BatchDetectFn) -> HealthDetector:
    return HealthDetector(detect_fn=detect_fn, per_team=False, kind="clickhouse_batch")


def resolve_execution_policy(
    detector: HealthDetector,
    *,
    batch_size: int | None = None,
    max_concurrent: int | None = None,
) -> HealthExecutionPolicy:
    base_policy = _DEFAULT_POLICY_BY_KIND[detector.kind]
    resolved = HealthExecutionPolicy(
        batch_size=batch_size if batch_size is not None else base_policy.batch_size,
        max_concurrent=max_concurrent if max_concurrent is not None else base_policy.max_concurrent,
    )

    if resolved.batch_size <= 0:
        raise ValueError(f"batch_size must be > 0, got {resolved.batch_size}")
    if resolved.max_concurrent <= 0:
        raise ValueError(f"max_concurrent must be > 0, got {resolved.max_concurrent}")

    return resolved
