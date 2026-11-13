from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.models.integration import Integration
from posthog.models.organization import Organization
from posthog.models.team.team import Team

from products.commands.backend.channels.slack.mentions import _installation_id


class TestInstallationId(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.other_org = Organization.objects.create(name="Other org")
        self.other_org_team = Team.objects.create(organization=self.other_org, name="Other org team")
        self.same_org_team = Team.objects.create(organization=self.organization, name="Same org team")

    def _install(self, team: Team, external_id: str, account: str, kind: str = "github") -> None:
        Integration.objects.create(
            team=team, kind=kind, integration_id=external_id, config={"account": {"name": account}}
        )

    @parameterized.expand(
        [
            ("same_case", "example-org", "100"),
            ("ignores_case", "EXAMPLE-ORG", "100"),
            ("unknown_owner", "someone-else", None),
        ]
    )
    def test_reads_the_installation_of_the_owner_in_the_connected_organizations(
        self, _name: str, owner: str, expected: str | None
    ) -> None:
        self._install(self.team, "100", "example-org")
        self._install(self.other_org_team, "999", "example-org")

        assert _installation_id(owner, [str(self.organization.id)]) == expected

    def test_the_newest_installation_wins_and_other_kinds_are_ignored(self) -> None:
        self._install(self.team, "100", "example-org")
        self._install(self.same_org_team, "200", "example-org")
        self._install(self.team, "300", "example-org", kind="slack")

        assert _installation_id("example-org", [str(self.organization.id)]) == "200"

    def test_no_organizations_finds_nothing(self) -> None:
        self._install(self.team, "100", "example-org")

        assert _installation_id("example-org", []) is None
