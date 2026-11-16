from __future__ import annotations

import json
import hashlib
from typing import TYPE_CHECKING, ClassVar

import structlog

from posthog.dataclasses import frozen
from posthog.models.health_issue import HealthIssue
from posthog.temporal.health_checks.detectors import CLICKHOUSE_BATCH_EXECUTION_POLICY, HealthExecutionPolicy
from posthog.temporal.health_checks.framework import HealthCheck
from posthog.temporal.health_checks.models import HealthCheckBatchSkipped, HealthCheckResult
from posthog.temporal.health_checks.rollups.freshness import RollupWindow, rollup_window

if TYPE_CHECKING:
    from django.db import models

logger = structlog.get_logger(__name__)

# A batch reads Postgres rollup rows, not raw events, so it holds as many teams as a Postgres check.
# That size also bounds the issue upserts, which take one advisory lock per team in one transaction.
ROLLUP_EXECUTION_POLICY = HealthExecutionPolicy(batch_size=1000, max_concurrent=2)

COMPARISON_SAMPLE_RATE = 0.1
_COMPARISON_LOG_TEAMS = 20


@frozen
class RollupComparison:
    """How the rollup's issues for a sample of teams differ from the raw-event issues.

    `different_issues` counts teams whose issue identities differ. `different_payloads` counts teams with
    the same identities but a different severity or payload, such as other hostnames or counts.
    """

    sampled_teams: int
    both_flagged: int
    only_rollup: list[int]
    only_events: list[int]
    different_issues: list[int]
    different_payloads: list[int]


def compare_issues(
    kind: str,
    sample: list[int],
    rollup_issues: dict[int, list[HealthCheckResult]],
    event_issues: dict[int, list[HealthCheckResult]],
) -> RollupComparison:
    def identities(results: list[HealthCheckResult]) -> set[str]:
        return {HealthIssue.compute_unique_hash(kind, result.payload, result.hash_keys) for result in results}

    def contents(results: list[HealthCheckResult]) -> set[str]:
        return {
            json.dumps({"severity": result.severity, "payload": result.payload}, sort_keys=True, default=str)
            for result in results
        }

    only_rollup: list[int] = []
    only_events: list[int] = []
    different_issues: list[int] = []
    different_payloads: list[int] = []
    both_flagged = 0
    for team_id in sample:
        from_rollup = rollup_issues.get(team_id, [])
        from_events = event_issues.get(team_id, [])
        if from_rollup and not from_events:
            only_rollup.append(team_id)
        elif from_events and not from_rollup:
            only_events.append(team_id)
        elif identities(from_rollup) != identities(from_events):
            different_issues.append(team_id)
        elif from_rollup:
            both_flagged += 1
            if contents(from_rollup) != contents(from_events):
                different_payloads.append(team_id)
    return RollupComparison(
        sampled_teams=len(sample),
        both_flagged=both_flagged,
        only_rollup=only_rollup,
        only_events=only_events,
        different_issues=different_issues,
        different_payloads=different_payloads,
    )


class RollupHealthCheck(HealthCheck):
    """A health check that reads a daily rollup instead of raw events.

    `detect` resolves the window ending at the latest published day and calls `detect_from_rollup`.
    When the rollup is stale or the window has a gap, the batch is skipped, so every team keeps its
    current issues instead of reading as healthy.

    A check moving onto the rollup sets `reads_rollup = False` and keeps its raw-event query as
    `detect_from_events`. Its issues then still come from raw events, in ClickHouse-sized batches,
    and each batch also runs the rollup on a sample of teams and logs where the two disagree.
    Remove `reads_rollup = False` and delete `detect_from_events` once the comparison looks right.
    """

    rollup_model: ClassVar[type[models.Model]]
    window_days: ClassVar[int]
    reads_rollup: ClassVar[bool] = True
    policy = ROLLUP_EXECUTION_POLICY

    def __init_subclass__(cls, **kwargs: object) -> None:
        # Set before HealthCheck registers the subclass, because registration reads the policy.
        if not cls.reads_rollup and "policy" not in cls.__dict__:
            cls.policy = CLICKHOUSE_BATCH_EXECUTION_POLICY
        super().__init_subclass__(**kwargs)

    def detect(self, team_ids: list[int]) -> dict[int, list[HealthCheckResult]]:
        if not self.reads_rollup:
            issues = self.detect_from_events(team_ids)
            self._compare_with_rollup(team_ids, issues)
            return issues
        window = rollup_window(self.rollup_model, self.window_days)
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

    def _compare_with_rollup(self, team_ids: list[int], event_issues: dict[int, list[HealthCheckResult]]) -> None:
        # The comparison only logs, so no failure in it may stop the raw-event issues.
        try:
            window = rollup_window(self.rollup_model, self.window_days)
            if window is None:
                return
            sample = self._comparison_sample(team_ids, window)
            if not sample:
                return
            comparison = compare_issues(self.kind, sample, self.detect_from_rollup(sample, window), event_issues)
        except Exception:
            logger.exception("health check rollup comparison failed", kind=self.kind)
            return

        disagreements = len(comparison.only_rollup) + len(comparison.only_events) + len(comparison.different_issues)
        logger.info(
            "health check rollup comparison",
            kind=self.kind,
            window_start=window.start.isoformat(),
            window_end=window.end.isoformat(),
            sampled_teams=comparison.sampled_teams,
            agreement_rate=round(1 - disagreements / comparison.sampled_teams, 4),
            both_flagged=comparison.both_flagged,
            only_rollup=len(comparison.only_rollup),
            only_events=len(comparison.only_events),
            different_issues=len(comparison.different_issues),
            different_payloads=len(comparison.different_payloads),
            only_rollup_team_ids=comparison.only_rollup[:_COMPARISON_LOG_TEAMS],
            only_events_team_ids=comparison.only_events[:_COMPARISON_LOG_TEAMS],
            different_issues_team_ids=comparison.different_issues[:_COMPARISON_LOG_TEAMS],
            different_payloads_team_ids=comparison.different_payloads[:_COMPARISON_LOG_TEAMS],
        )
