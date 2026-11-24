from posthog.test.base import BaseTest

from posthog.models import Team

from products.customer_analytics.backend.facade.api import list_logo_domains_across_teams
from products.customer_analytics.backend.models import Account


class TestListLogoDomainsAcrossTeams(BaseTest):
    def test_lists_each_accounts_logo_domain_from_every_team_once(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="other accounts team")
        Account.objects.unscoped().create(team=self.team, name="Acme", _properties={"website_domain": "acme.example"})
        Account.objects.unscoped().create(
            team=other_team, name="Acme again", _properties={"website_domain": "acme.example"}
        )
        Account.objects.unscoped().create(
            team=other_team,
            name="Globex",
            _properties={"email_domains": ["gmail.com", "globex.example"]},
        )
        Account.objects.unscoped().create(team=self.team, name="No domain", _properties={})

        assert list_logo_domains_across_teams() == ["acme.example", "globex.example"]
