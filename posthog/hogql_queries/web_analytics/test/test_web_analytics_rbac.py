from posthog.test.base import APIBaseTest

from posthog.schema import DateRange, WebOverviewQuery

from posthog.constants import AvailableFeature
from posthog.hogql_queries.web_analytics.web_overview import WebOverviewQueryRunner
from posthog.rbac.user_access_control import UserAccessControlError

try:
    from products.enterprise.backend.models.rbac.access_control import AccessControl
except ImportError:
    pass


class TestWebAnalyticsRBAC(APIBaseTest):
    def test_validate_query_runner_access_with_viewer(self):
        query = WebOverviewQuery(
            dateRange=DateRange(date_from="2024-01-01", date_to="2024-01-31"),
            properties=[],
        )
        runner = WebOverviewQueryRunner(team=self.team, query=query)

        # By default, users should have access
        assert runner.validate_query_runner_access(self.user)

    def test_validate_query_runner_access_with_editor(self):
        AccessControl.objects.create(team=self.team, resource="web_analytics", access_level="editor")
        self.organization.available_product_features.append({"key": AvailableFeature.ADVANCED_PERMISSIONS})  # type: ignore[union-attr]
        self.organization.save()

        query = WebOverviewQuery(
            dateRange=DateRange(date_from="2024-01-01", date_to="2024-01-31"),
            properties=[],
        )
        runner = WebOverviewQueryRunner(team=self.team, query=query)

        assert runner.validate_query_runner_access(self.user)

    def test_validate_query_runner_access_without_access(self):
        AccessControl.objects.create(team=self.team, resource="web_analytics", access_level="none")
        self.organization.available_product_features.append({"key": AvailableFeature.ADVANCED_PERMISSIONS})  # type: ignore[union-attr]
        self.organization.save()

        query = WebOverviewQuery(
            dateRange=DateRange(date_from="2024-01-01", date_to="2024-01-31"),
            properties=[],
        )
        runner = WebOverviewQueryRunner(team=self.team, query=query)

        with self.assertRaises(UserAccessControlError):
            runner.validate_query_runner_access(self.user)

    def test_validate_query_runner_access_with_manager(self):
        AccessControl.objects.create(team=self.team, resource="web_analytics", access_level="manager")
        self.organization.available_product_features.append({"key": AvailableFeature.ADVANCED_PERMISSIONS})  # type: ignore[union-attr]
        self.organization.save()

        query = WebOverviewQuery(
            dateRange=DateRange(date_from="2024-01-01", date_to="2024-01-31"),
            properties=[],
        )
        runner = WebOverviewQueryRunner(team=self.team, query=query)

        assert runner.validate_query_runner_access(self.user)
