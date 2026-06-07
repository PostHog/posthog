from posthog.test.base import BaseTest

from posthog.models.gateway import DEFAULT_GATEWAY_SLUG, Gateway
from posthog.models.gateway_provisioning import provision_default_gateway
from posthog.models.organization import Organization
from posthog.models.team.team import Team


class TestGatewayProvisioning(BaseTest):
    def _defaults_for(self, team: Team) -> list[Gateway]:
        return list(Gateway.all_teams.filter(team=team, is_default=True))

    def test_team_creation_provisions_default_gateway(self):
        team = Team.objects.create(organization=self.organization, name="fresh")
        defaults = self._defaults_for(team)
        self.assertEqual(len(defaults), 1)
        self.assertEqual(defaults[0].slug, DEFAULT_GATEWAY_SLUG)

    def test_basetest_team_was_provisioned(self):
        # The signal runs during BaseTest.setUp too.
        self.assertEqual(len(self._defaults_for(self.team)), 1)

    def test_provisioning_is_idempotent(self):
        team = Team.objects.create(organization=self.organization, name="fresh")
        provision_default_gateway(team.id)
        provision_default_gateway(team.id)
        self.assertEqual(len(self._defaults_for(team)), 1)

    def test_child_environment_shares_parent_default(self):
        parent = Team.objects.create(organization=self.organization, name="parent")
        child = Team.objects.create(organization=self.organization, name="child", parent_team=parent)
        # The child resolves to the parent's gateway; it must not mint its own.
        self.assertEqual(len(self._defaults_for(child)), 0)
        self.assertEqual(len(self._defaults_for(parent)), 1)

    def test_provisions_per_team_across_orgs(self):
        other_org = Organization.objects.create(name="other org")
        team_a = Team.objects.create(organization=self.organization, name="a")
        team_b = Team.objects.create(organization=other_org, name="b")
        self.assertEqual(len(self._defaults_for(team_a)), 1)
        self.assertEqual(len(self._defaults_for(team_b)), 1)
