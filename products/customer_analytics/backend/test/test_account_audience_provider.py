from posthog.test.base import ClickhouseTestMixin, NonAtomicBaseTest

from django.test import override_settings

from products.customer_analytics.backend.test.factories import create_account
from products.workflows.backend.facade.testing import (
    count_account_audience_for_test,
    list_account_audience_page_for_test,
)


@override_settings(IN_UNIT_TESTING=True)
class TestAccountAudienceProviderWiring(ClickhouseTestMixin, NonAtomicBaseTest):
    def test_workflows_service_resolves_through_the_registered_provider(self):
        create_account(team_id=self.team.id, name="A", external_id="a1")
        create_account(team_id=self.team.id, name="No key", external_id=None)

        filters = {"audience_type": "accounts"}
        assert list_account_audience_page_for_test(team_id=self.team.id, filters=filters, cursor=None) == ["a1"]
        assert count_account_audience_for_test(team_id=self.team.id, filters=filters) == 1
