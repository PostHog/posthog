from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from posthog.temporal.health_checks.framework import HealthCheckRegistration

from posthog.dags.common.health.types import (
    BatchResult as BatchResult,
    HealthCheckResult as HealthCheckResult,
)

BatchDetectFn = Callable[[list[int]], dict[int, list[HealthCheckResult]]]


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
