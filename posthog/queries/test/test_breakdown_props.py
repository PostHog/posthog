from posthog.test.base import BaseTest

from posthog.models.cohort.cohort import Cohort
from posthog.models.organization import Organization
from posthog.models.team import Team
from posthog.queries.breakdown_props import ALL_USERS_COHORT_ID, NOT_IN_COHORT_ID, resolve_cohort_names


class TestResolveCohortNames(BaseTest):
    def test_resolves_real_cohort_ids_in_one_query(self):
        cohort_a = Cohort.objects.create(team=self.team, name="Paying users", groups=[])
        cohort_b = Cohort.objects.create(team=self.team, name="Churned users", groups=[])

        with self.assertNumQueries(1):
            result = resolve_cohort_names([cohort_a.pk, cohort_b.pk], self.team)

        self.assertEqual(result, {cohort_a.pk: "Paying users", cohort_b.pk: "Churned users"})

    def test_includes_sentinel_ids(self):
        result = resolve_cohort_names([ALL_USERS_COHORT_ID, NOT_IN_COHORT_ID], self.team)

        self.assertEqual(result[ALL_USERS_COHORT_ID], "all users")
        self.assertEqual(result[NOT_IN_COHORT_ID], "Not in cohort")

    def test_returns_empty_map_for_no_ids(self):
        with self.assertNumQueries(0):
            self.assertEqual(resolve_cohort_names([], self.team), {})

    def test_skips_unknown_ids(self):
        cohort = Cohort.objects.create(team=self.team, name="Known", groups=[])
        result = resolve_cohort_names([cohort.pk, 9_999_999], self.team)
        self.assertEqual(result, {cohort.pk: "Known"})

    def test_scoped_to_team_project(self):
        other_org = Organization.objects.create(name="Other org")
        other_team = Team.objects.create(organization=other_org, name="Other team")
        foreign_cohort = Cohort.objects.create(team=other_team, name="Foreign", groups=[])
        result = resolve_cohort_names([foreign_cohort.pk], self.team)
        self.assertEqual(result, {})
