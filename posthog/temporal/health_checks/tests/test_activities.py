from datetime import timedelta

from posthog.test.base import BaseTest

from django.utils import timezone

from posthog.models.health_issue import HealthIssue
from posthog.temporal.health_checks.activities import select_team_ids
from posthog.temporal.health_checks.models import HealthCheckWorkflowInputs

KIND = "test_kind"


class TestSelectTeamIds(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.user.last_login = timezone.now() - timedelta(days=90)
        self.user.save()

    def _selected_team_ids(self) -> set[int]:
        return set(select_team_ids(HealthCheckWorkflowInputs(name=KIND, kind=KIND, active_since_days=30)))

    def _seed_issue(self, kind: str, status: str) -> None:
        HealthIssue.objects.create(
            team=self.team,
            kind=kind,
            severity=HealthIssue.Severity.CRITICAL,
            payload={},
            unique_hash="h1",
            status=status,
        )

    def test_skips_team_outside_active_window(self):
        self.assertNotIn(self.team.id, self._selected_team_ids())

    def test_includes_inactive_team_with_open_issue_of_this_kind(self):
        self._seed_issue(KIND, HealthIssue.Status.ACTIVE)
        self.assertIn(self.team.id, self._selected_team_ids())

    def test_skips_inactive_team_whose_issue_is_resolved(self):
        self._seed_issue(KIND, HealthIssue.Status.RESOLVED)
        self.assertNotIn(self.team.id, self._selected_team_ids())

    def test_skips_inactive_team_with_open_issue_of_another_kind(self):
        self._seed_issue("other_kind", HealthIssue.Status.ACTIVE)
        self.assertNotIn(self.team.id, self._selected_team_ids())

    def test_includes_team_inside_active_window(self):
        self.user.last_login = timezone.now()
        self.user.save()
        self.assertIn(self.team.id, self._selected_team_ids())
