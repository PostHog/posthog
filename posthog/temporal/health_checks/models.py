from __future__ import annotations

import dataclasses
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from posthog.temporal.health_checks.framework import HealthCheckRegistration

from posthog.models.health_issue import HealthIssue

BatchDetectFn = Callable[[list[int]], dict[int, list["HealthCheckResult"]]]


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
    detect_duration: float = 0.0
    db_write_duration: float = 0.0
    resolve_duration: float = 0.0

    @property
    def total_duration(self) -> float:
        return self.detect_duration + self.db_write_duration + self.resolve_duration

    @property
    def teams_per_second(self) -> float:
        return self.batch_size / self.total_duration if self.total_duration > 0 else 0

    @property
    def not_processed_rate(self) -> float:
        return (self.teams_failed + self.teams_skipped) / self.batch_size if self.batch_size > 0 else 0

    def __iadd__(self, other: BatchResult) -> BatchResult:
        for f in dataclasses.fields(self):
            setattr(self, f.name, getattr(self, f.name) + getattr(other, f.name))
        return self


@dataclass
class HealthCheckWorkflowInputs:
    name: str
    kind: str
    batch_size: int = 250
    max_concurrent: int = 1
    team_ids: list[int] | None = None
    rollout_percentage: float = 1.0
    not_processed_threshold: float = 0.1
    dry_run: bool = False
    owner: str = ""

    @classmethod
    def from_config(cls, config: HealthCheckRegistration) -> HealthCheckWorkflowInputs:
        return cls(
            name=config.name,
            kind=config.kind,
            batch_size=config.batch_size,
            max_concurrent=config.max_concurrent,
            rollout_percentage=config.rollout_percentage,
            not_processed_threshold=config.not_processed_threshold,
            dry_run=config.dry_run,
            owner=config.owner.value,
        )


class HealthCheckThresholdExceeded(Exception):
    pass
