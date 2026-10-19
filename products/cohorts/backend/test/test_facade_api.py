from posthog.test.base import BaseTest
from unittest.mock import MagicMock, call, patch

from posthog.models.team import Team

from products.cohorts.backend.facade.api import cohort_exists_for_team
from products.cohorts.backend.models.cohort import Cohort
from products.cohorts.backend.tasks import reconcile_static_cohort_count_after_addition


class TestCohortExistsForTeam(BaseTest):
    def test_a_cohort_is_only_visible_to_its_own_team(self) -> None:
        cohort = Cohort.objects.create(team=self.team, name="Churn risk")
        other_team = Team.objects.create(organization=self.organization, name="Other")

        assert cohort_exists_for_team(team_id=self.team.id, cohort_id=cohort.id)
        assert not cohort_exists_for_team(team_id=other_team.id, cohort_id=cohort.id)

    def test_a_soft_deleted_cohort_still_counts(self) -> None:
        cohort = Cohort.objects.create(team=self.team, name="Churn risk", deleted=True)

        assert cohort_exists_for_team(team_id=self.team.id, cohort_id=cohort.id)


class TestReconcileStaticCohortCountAfterAddition(BaseTest):
    @patch("products.cohorts.backend.tasks.count_cohort_members", side_effect=[11, 9])
    def test_repairs_an_undercount_without_overwriting_a_newer_count(self, count_cohort_members: MagicMock) -> None:
        cohort = Cohort.objects.create(team=self.team, name="Contacted", is_static=True, count=10)

        reconcile_static_cohort_count_after_addition(team_id=self.team.id, cohort_id=cohort.id)
        cohort.refresh_from_db()
        assert cohort.count == 11

        reconcile_static_cohort_count_after_addition(team_id=self.team.id, cohort_id=cohort.id)
        cohort.refresh_from_db()
        assert cohort.count == 11
        assert count_cohort_members.call_args_list == [
            call(team_id=self.team.id, cohort_id=cohort.id, consistency="strong"),
            call(team_id=self.team.id, cohort_id=cohort.id, consistency="strong"),
        ]
