from posthog.test.base import ClickhouseTestMixin, NonAtomicBaseTest

from django.test import override_settings

from products.customer_analytics.backend.test.factories import create_account
from products.workflows.backend.services.account_audience import get_account_audience_count, get_account_audience_page


@override_settings(IN_UNIT_TESTING=True)
class TestAccountAudienceProviderWiring(ClickhouseTestMixin, NonAtomicBaseTest):
    def test_workflows_service_resolves_through_the_registered_provider(self):
        create_account(team_id=self.team.id, name="A", external_id="a1")
        create_account(team_id=self.team.id, name="No key", external_id=None)

        filters = {"audience_type": "accounts"}
        assert get_account_audience_page(self.team, filters, cursor=None) == ["a1"]
        assert get_account_audience_count(self.team, filters) == 1
