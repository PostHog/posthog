from posthog.test.base import BaseTest
from unittest.mock import patch

from posthog.models.health_check_run import HealthCheckRun
from posthog.models.health_issue import HealthIssue
from posthog.temporal.health_checks.models import HealthCheckResult
from posthog.temporal.health_checks.processing import _process_batch_detection


def _issue() -> HealthCheckResult:
    return HealthCheckResult(severity=HealthIssue.Severity.WARNING, payload={"detail": "x"}, hash_keys=[])


@patch("posthog.temporal.health_checks.processing.emit_health_check_signals")
@patch("posthog.temporal.health_checks.processing.emit_health_check_alert")
class TestRunRecording(BaseTest):
    def test_records_a_run_for_a_team_with_no_issues(self, _alert, _signals):
        _process_batch_detection([self.team.id], "test_kind", lambda team_ids: {})

        run = HealthCheckRun.objects.get(team=self.team, kind="test_kind")
        self.assertFalse(run.found_issues)

    def test_records_a_run_for_a_team_with_issues(self, _alert, _signals):
        _process_batch_detection([self.team.id], "test_kind", lambda team_ids: {self.team.id: [_issue()]})

        run = HealthCheckRun.objects.get(team=self.team, kind="test_kind")
        self.assertTrue(run.found_issues)

    def test_a_later_run_updates_the_row_in_place(self, _alert, _signals):
        _process_batch_detection([self.team.id], "test_kind", lambda team_ids: {self.team.id: [_issue()]})
        first_run_at = HealthCheckRun.objects.get(team=self.team, kind="test_kind").last_run_at

        _process_batch_detection([self.team.id], "test_kind", lambda team_ids: {})

        runs = HealthCheckRun.objects.filter(team=self.team, kind="test_kind")
        self.assertEqual(runs.count(), 1)
        self.assertGreater(runs[0].last_run_at, first_run_at)
        self.assertFalse(runs[0].found_issues)

    def test_a_dry_run_records_nothing(self, _alert, _signals):
        _process_batch_detection([self.team.id], "test_kind", lambda team_ids: {}, dry_run=True)

        self.assertFalse(HealthCheckRun.objects.filter(team=self.team).exists())

    def test_skips_a_team_deleted_mid_batch(self, _alert, _signals):
        missing_team_id = self.team.id + 999_999

        _process_batch_detection([self.team.id, missing_team_id], "test_kind", lambda team_ids: {})

        self.assertEqual(
            set(HealthCheckRun.objects.filter(kind="test_kind").values_list("team_id", flat=True)), {self.team.id}
        )
