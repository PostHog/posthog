from posthog.test.base import BaseTest

from posthog.hogql.database.schema.marketing_costs_precomputed import costs_dedup_v2_enabled

from posthog.models.team import Team


class TestCostsDedupV2Flag(BaseTest):
    def test_reads_the_organization_id_off_the_team_without_a_query(self):
        # The flag sits on the cache-key path of every query. A `team.organization` dereference here
        # costs one Postgres query per cache-key build, and raises when the organization row is gone.
        team = Team.objects.get(pk=self.team.pk)

        with self.assertNumQueries(0):
            assert costs_dedup_v2_enabled(team) is False
