from posthog.test.base import BaseTest

from posthog.models.team import Team

from products.cohorts.backend.facade.api import cohort_exists_for_team
from products.cohorts.backend.models.cohort import Cohort


class TestCohortExistsForTeam(BaseTest):
    def test_a_cohort_is_only_visible_to_its_own_team(self) -> None:
        cohort = Cohort.objects.create(team=self.team, name="Churn risk")
        other_team = Team.objects.create(organization=self.organization, name="Other")

        assert cohort_exists_for_team(team_id=self.team.id, cohort_id=cohort.id)
        assert not cohort_exists_for_team(team_id=other_team.id, cohort_id=cohort.id)

    def test_a_soft_deleted_cohort_still_counts(self) -> None:
        cohort = Cohort.objects.create(team=self.team, name="Churn risk", deleted=True)

        assert cohort_exists_for_team(team_id=self.team.id, cohort_id=cohort.id)
