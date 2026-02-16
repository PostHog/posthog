import dataclasses
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Optional

import dagster

from posthog.models.health_issue import HealthIssue

BatchDetectFn = Callable[[list[int], dagster.OpExecutionContext], dict[int, list["HealthCheckResult"]]]
TeamDetectFn = Callable[[int, dagster.OpExecutionContext], Optional[list["HealthCheckResult"]]]


@dataclass
class HealthCheckResult:
    severity: HealthIssue.Severity
    payload: dict[str, Any]
    hash_keys: list[str] | None = None

    def __post_init__(self) -> None:
        valid = set(HealthIssue.Severity.values)
        if self.severity not in valid:
            raise ValueError(f"Invalid severity '{self.severity}', must be one of: {', '.join(sorted(valid))}")


@dataclass
class BatchResult:
    batch_size: int = 0
    issues_upserted: int = 0
    issues_resolved: int = 0
    teams_with_issues: int = 0
    teams_healthy: int = 0
    teams_failed: int = 0
    teams_skipped: int = 0
    detect_duration: float = 0
    db_write_duration: float = 0
    resolve_duration: float = 0

    @property
    def total_duration(self) -> float:
        return self.detect_duration + self.db_write_duration + self.resolve_duration

    # Adds up all the fields without needing to be explicit
    # This allows us to do things like batchresult = batchresult + 1
    # to increment every value by 1
    def __iadd__(self, other: "BatchResult") -> "BatchResult":
        for f in dataclasses.fields(self):
            setattr(self, f.name, getattr(self, f.name) + getattr(other, f.name))
        return self


@dataclass
class HealthCheckDefinition:
    job: dagster.JobDefinition
    schedule: dagster.ScheduleDefinition | None


class HealthCheckThresholdExceeded(Exception):
    pass
