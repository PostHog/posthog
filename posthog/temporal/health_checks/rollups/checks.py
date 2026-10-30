from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, ClassVar

import structlog

from posthog.models.health_issue import HealthIssue
from posthog.temporal.health_checks.detectors import HealthExecutionPolicy
from posthog.temporal.health_checks.framework import HealthCheck
from posthog.temporal.health_checks.models import HealthCheckBatchSkipped, HealthCheckResult
from posthog.temporal.health_checks.rollups.freshness import RollupWindow, rollup_window

if TYPE_CHECKING:
    from django.db import models

logger = structlog.get_logger(__name__)

# A batch reads Postgres rollup rows, not raw events, so it can hold many more teams than a ClickHouse check.
ROLLUP_EXECUTION_POLICY = HealthExecutionPolicy(batch_size=2500, max_concurrent=2)

COMPARISON_SAMPLE_RATE = 0.1
_COMPARISON_LOG_TEAMS = 20


class RollupHealthCheck(HealthCheck):
    """A health check that reads a daily rollup instead of raw events.

    `detect` resolves the window ending at the latest published day and calls `detect_from_rollup`.
    When the rollup is stale or the window has a gap, the batch is skipped, so every team keeps its
    current issues instead of reading as healthy.

    A check moving onto the rollup sets `reads_rollup = False` and keeps its raw-event query as
    `detect_from_events`. Its issues then still come from raw events, and each batch also runs the
    rollup on a sample of teams and logs where the two disagree. Set `reads_rollup = True` and
    delete `detect_from_events` once the comparison looks right.
    """

    rollup_model: ClassVar[type[models.Model]]
    window_days: ClassVar[int]
    reads_rollup: ClassVar[bool] = True
    policy = ROLLUP_EXECUTION_POLICY

    def detect(self, team_ids: list[int]) -> dict[int, list[HealthCheckResult]]:
        window = rollup_window(self.rollup_model, self.window_days)
        if not self.reads_rollup:
            issues = self.detect_from_events(team_ids)
            if window is not None:
                self._compare_with_rollup(team_ids, issues, window)
            return issues
        if window is None:
            raise HealthCheckBatchSkipped(
                f"{self.rollup_model._meta.db_table} has no fresh {self.window_days}-day window"
            )
        return self.detect_from_rollup(team_ids, window)

    def detect_from_rollup(self, team_ids: list[int], window: RollupWindow) -> dict[int, list[HealthCheckResult]]:
        raise NotImplementedError

    def detect_from_events(self, team_ids: list[int]) -> dict[int, list[HealthCheckResult]]:
        raise NotImplementedError

    def _comparison_sample(self, team_ids: list[int], window: RollupWindow) -> list[int]:
        # Hashing the window end with the team id picks a different sample each day, and the same one on a retry.
        threshold = int(COMPARISON_SAMPLE_RATE * 2**32)
        return [
            team_id
            for team_id in team_ids
            if int.from_bytes(hashlib.sha256(f"{window.end}:{team_id}".encode()).digest()[:4], "big") < threshold
        ]

    def _compare_with_rollup(
        self, team_ids: list[int], event_issues: dict[int, list[HealthCheckResult]], window: RollupWindow
    ) -> None:
        sample = self._comparison_sample(team_ids, window)
        if not sample:
            return
        try:
            rollup_issues = self.detect_from_rollup(sample, window)
        except Exception:
            logger.exception("health check rollup comparison failed", kind=self.kind)
            return

        def hashes(results: list[HealthCheckResult]) -> set[str]:
            return {HealthIssue.compute_unique_hash(self.kind, r.payload, r.hash_keys) for r in results}

        only_rollup: list[int] = []
        only_events: list[int] = []
        different_issues: list[int] = []
        both_flagged = 0
        for team_id in sample:
            rollup_hashes = hashes(rollup_issues.get(team_id, []))
            event_hashes = hashes(event_issues.get(team_id, []))
            if rollup_hashes and not event_hashes:
                only_rollup.append(team_id)
            elif event_hashes and not rollup_hashes:
                only_events.append(team_id)
            elif rollup_hashes != event_hashes:
                different_issues.append(team_id)
            elif rollup_hashes:
                both_flagged += 1

        disagreements = len(only_rollup) + len(only_events) + len(different_issues)
        logger.info(
            "health check rollup comparison",
            kind=self.kind,
            window_start=window.start.isoformat(),
            window_end=window.end.isoformat(),
            sampled_teams=len(sample),
            agreement_rate=round(1 - disagreements / len(sample), 4),
            both_flagged=both_flagged,
            only_rollup=len(only_rollup),
            only_events=len(only_events),
            different_issues=len(different_issues),
            only_rollup_team_ids=only_rollup[:_COMPARISON_LOG_TEAMS],
            only_events_team_ids=only_events[:_COMPARISON_LOG_TEAMS],
            different_issues_team_ids=different_issues[:_COMPARISON_LOG_TEAMS],
        )
