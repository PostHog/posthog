from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from posthog.temporal.health_checks.detectors import HealthExecutionPolicy
from posthog.temporal.health_checks.framework import HealthCheck
from posthog.temporal.health_checks.models import HealthCheckBatchSkipped, HealthCheckResult
from posthog.temporal.health_checks.rollups.freshness import RollupWindow, rollup_window

if TYPE_CHECKING:
    from django.db import models

# A batch reads Postgres rollup rows, not raw events, so it can hold many more teams than a ClickHouse check.
ROLLUP_EXECUTION_POLICY = HealthExecutionPolicy(batch_size=2500, max_concurrent=2)


class RollupHealthCheck(HealthCheck):
    """A health check that reads a daily rollup instead of raw events.

    `detect` resolves the window ending at the latest published day and calls `detect_from_rollup`.
    When the rollup is stale or the window has a gap, the batch is skipped, so every team keeps its
    current issues instead of reading as healthy.
    """

    rollup_model: ClassVar[type[models.Model]]
    window_days: ClassVar[int]
    policy = ROLLUP_EXECUTION_POLICY

    def detect(self, team_ids: list[int]) -> dict[int, list[HealthCheckResult]]:
        window = rollup_window(self.rollup_model, self.window_days)
        if window is None:
            raise HealthCheckBatchSkipped(
                f"{self.rollup_model._meta.db_table} has no fresh {self.window_days}-day window"
            )
        return self.detect_from_rollup(team_ids, window)

    def detect_from_rollup(self, team_ids: list[int], window: RollupWindow) -> dict[int, list[HealthCheckResult]]:
        raise NotImplementedError
