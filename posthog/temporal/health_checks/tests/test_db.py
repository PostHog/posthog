from datetime import UTC, datetime

import time_machine
from posthog.test.base import BaseTest

from posthog.models.health_issue import HealthCheckLastRun, HealthIssue
from posthog.models.team import Team
from posthog.temporal.health_checks.db import resolve_stale_issues_with_deltas, upsert_issues_with_deltas
from posthog.temporal.health_checks.models import HealthCheckResult
from posthog.temporal.health_checks.processing import _process_batch_detection


class TestResolveStaleIssuesWithDeltas(BaseTest):
    def _seed_active_issue(self, kind: str, unique_hash: str) -> HealthIssue:
        return HealthIssue.objects.create(
            team=self.team,
            kind=kind,
            severity=HealthIssue.Severity.WARNING,
            payload={},
            unique_hash=unique_hash,
            status=HealthIssue.Status.ACTIVE,
        )

    def test_resolves_issues_for_existing_teams(self):
        self._seed_active_issue("test_kind", "h1")
        resolved = resolve_stale_issues_with_deltas("test_kind", {}, healthy_team_ids={self.team.id})
        self.assertEqual({i.unique_hash for i in resolved}, {"h1"})

    def test_skips_deleted_team_id_in_healthy_set(self):
        missing_team_id = self.team.id + 999_999
        self._seed_active_issue("test_kind", "h1")
        resolved = resolve_stale_issues_with_deltas(
            "test_kind",
            {},
            healthy_team_ids={self.team.id, missing_team_id},
        )
        self.assertEqual({i.unique_hash for i in resolved}, {"h1"})

    def test_upsert_skips_deleted_team_without_aborting_batch(self):
        # Reproduces the production failure: a team_id snapshotted at workflow
        # start is deleted before the upsert runs. The deferred FK check used
        # to fire at COMMIT and roll back the live team's issue along with the
        # orphan. After the fix the orphan is filtered out and the live team's
        # issue persists.
        missing_team_id = self.team.id + 999_999
        issues_by_team = {
            self.team.id: [
                HealthCheckResult(severity=HealthIssue.Severity.WARNING, payload={"detail": "x"}, hash_keys=[])
            ],
            missing_team_id: [
                HealthCheckResult(severity=HealthIssue.Severity.WARNING, payload={"detail": "y"}, hash_keys=[])
            ],
        }

        created = upsert_issues_with_deltas("test_kind", issues_by_team)
        self.assertEqual({i.team_id for i in created}, {self.team.id})
        self.assertTrue(
            HealthIssue.objects.filter(team=self.team, kind="test_kind", status=HealthIssue.Status.ACTIVE).exists()
        )
        self.assertFalse(HealthIssue.objects.filter(team_id=missing_team_id).exists())


class TestRecordHealthCheckRuns(BaseTest):
    def test_batch_records_healthy_and_failing_teams_and_updates_on_rerun(self):
        failing_team = Team.objects.create(organization=self.organization, project=self.project)
        missing_team_id = self.team.id + 999_999

        def detect(team_ids: list[int]) -> dict[int, list[HealthCheckResult]]:
            return {
                failing_team.id: [HealthCheckResult(severity=HealthIssue.Severity.WARNING, payload={}, hash_keys=[])]
            }

        for day in (1, 2):
            with time_machine.travel(datetime(2026, 1, day, tzinfo=UTC), tick=False):
                _process_batch_detection([self.team.id, failing_team.id, missing_team_id], "test_kind", detect)

        rows = dict(
            HealthCheckLastRun.objects.unscoped().filter(kind="test_kind").values_list("team_id", "last_checked_at")
        )
        self.assertEqual(
            rows,
            {self.team.id: datetime(2026, 1, 2, tzinfo=UTC), failing_team.id: datetime(2026, 1, 2, tzinfo=UTC)},
        )
