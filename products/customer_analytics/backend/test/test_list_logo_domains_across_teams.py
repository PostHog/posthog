from posthog.test.base import BaseTest

from posthog.models import Team

from products.customer_analytics.backend.logic.account_logo import list_logo_domains_across_teams
from products.customer_analytics.backend.models import Account


class TestListLogoDomainsAcrossTeams(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.other_team = Team.objects.create(organization=self.organization, name="other accounts team")

    def _create(self, team: Team, name: str, properties: dict) -> None:
        Account.objects.unscoped().create(team=team, name=name, _properties=properties)

    def test_lists_each_accounts_logo_domain_from_every_team_once_newest_first(self) -> None:
        self._create(self.team, "Acme", {"website_domain": "acme.example"})
        self._create(self.other_team, "Acme again", {"website_domain": "acme.example"})
        self._create(self.other_team, "Globex", {"email_domains": ["gmail.com", "globex.example"]})
        self._create(self.team, "No domain", {})

        domains = list_logo_domains_across_teams(limit=10, per_team_limit=10)

        assert domains == ["globex.example", "acme.example"]

    def test_caps_each_teams_share_and_lets_teams_take_turns(self) -> None:
        self._create(self.other_team, "Quiet", {"website_domain": "quiet.example"})
        for index in range(3):
            self._create(self.team, f"Busy {index}", {"website_domain": f"busy{index}.example"})

        assert list_logo_domains_across_teams(limit=10, per_team_limit=2) == [
            "busy2.example",
            "quiet.example",
            "busy1.example",
        ]
        assert list_logo_domains_across_teams(limit=2, per_team_limit=10) == ["busy2.example", "quiet.example"]
