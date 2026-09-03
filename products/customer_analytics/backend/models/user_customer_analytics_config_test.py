from posthog.test.base import BaseTest

from django.db import IntegrityError, transaction

from products.customer_analytics.backend.models import UserCustomerAnalyticsConfig
from products.customer_analytics.backend.models.team_scoped_test_base import TeamScopedTestMixin


class TestUserCustomerAnalyticsConfig(TeamScopedTestMixin, BaseTest):
    def test_config_is_unique_for_user_and_team(self) -> None:
        UserCustomerAnalyticsConfig.objects.create(team=self.team, user=self.user)

        with self.assertRaises(IntegrityError), transaction.atomic():
            UserCustomerAnalyticsConfig.objects.create(team=self.team, user=self.user)
