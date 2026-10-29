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

ROLLUP_EXECUTION_POLICY = HealthExecutionPolicy(batch_size=2500, max_concurrent=2)

COMPARISON_SAMPLE_RATE = 0.02
_COMPARISON_LOG_TEAMS = 20


class RollupHealthCheck(HealthCheck):
    """A health check that reads a daily rollup instead of raw events.

    `detect` resolves the window ending at the latest published day and calls `detect_from_rollup`.
    When the rollup is stale or the window has a gap, the batch is skipped, so every team keeps its
    current issues.

    While a check still implements `legacy_detect` (its raw-event query), each batch also runs it
    on a small sample of teams and logs where the two disagree. Delete `legacy_detect` once the
    comparison looks right and the check leaves dry run.
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
        issues = self.detect_from_rollup(team_ids, window)
        if type(self).legacy_detect is not RollupHealthCheck.legacy_detect:
            self._compare_with_legacy(team_ids, issues, window)
        return issues

    def detect_from_rollup(self, team_ids: list[int], window: RollupWindow) -> dict[int, list[HealthCheckResult]]:
        raise NotImplementedError

    def legacy_detect(self, team_ids: list[int]) -> dict[int, list[HealthCheckResult]]:
        raise NotImplementedError

    def _comparison_sample(self, team_ids: list[int], window: RollupWindow) -> list[int]:
        threshold = int(COMPARISON_SAMPLE_RATE * 2**32)
        return [
            team_id
            for team_id in team_ids
            if int.from_bytes(hashlib.sha256(f"{window.end}:{team_id}".encode()).digest()[:4], "big") < threshold
        ]

    def _compare_with_legacy(
        self, team_ids: list[int], issues: dict[int, list[HealthCheckResult]], window: RollupWindow
    ) -> None:
        sample = self._comparison_sample(team_ids, window)
        if not sample:
            return
        try:
            legacy = self.legacy_detect(sample)
        except Exception:
            logger.exception("health check rollup comparison failed", kind=self.kind)
            return

        def hashes(results: list[HealthCheckResult]) -> set[str]:
            return {HealthIssue.compute_unique_hash(self.kind, r.payload, r.hash_keys) for r in results}

        only_rollup: list[int] = []
        only_legacy: list[int] = []
        different_issues: list[int] = []
        both_flagged = 0
        for team_id in sample:
            rollup_hashes = hashes(issues.get(team_id, []))
            legacy_hashes = hashes(legacy.get(team_id, []))
            if rollup_hashes and not legacy_hashes:
                only_rollup.append(team_id)
            elif legacy_hashes and not rollup_hashes:
                only_legacy.append(team_id)
            elif rollup_hashes != legacy_hashes:
                different_issues.append(team_id)
            elif rollup_hashes:
                both_flagged += 1

        disagreements = len(only_rollup) + len(only_legacy) + len(different_issues)
        logger.info(
            "health check rollup comparison",
            kind=self.kind,
            window_start=window.start.isoformat(),
            window_end=window.end.isoformat(),
            sampled_teams=len(sample),
            agreement_rate=round(1 - disagreements / len(sample), 4),
            both_flagged=both_flagged,
            only_rollup=len(only_rollup),
            only_legacy=len(only_legacy),
            different_issues=len(different_issues),
            only_rollup_team_ids=only_rollup[:_COMPARISON_LOG_TEAMS],
            only_legacy_team_ids=only_legacy[:_COMPARISON_LOG_TEAMS],
            different_issues_team_ids=different_issues[:_COMPARISON_LOG_TEAMS],
        )
