"""
Security tests for sharing access tokens - ensuring they cannot be abused to access unauthorized resources.
"""

import json

from posthog.test.base import APIBaseTest

from posthog.models.dashboard import Dashboard
from posthog.models.insight import Insight
from posthog.models.sharing_configuration import SharingConfiguration


class SharingAccessTokenSecurityTest(APIBaseTest):
    """Test that sharing access tokens cannot be abused to access unauthorized resources."""

    dashboard: Dashboard = None  # type: ignore

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.dashboard = Dashboard.objects.create(team=cls.team, name="test dashboard", created_by=cls.user)

    def setUp(self):
        super().setUp()
        # Ensure we're not authenticated for all sharing token security tests
        self.client.logout()
        # Verify that we're actually logged out by testing access to a protected endpoint
        response = self.client.get(f"/api/environments/{self.team.id}/insights/")
        self.assertIn(
            response.status_code,
            [401, 403],
            f"Expected 401/403 for logged out user, got {response.status_code}. User may still be logged in!",
        )

    def test_sharing_access_token_cannot_access_insights_not_on_dashboard(self):
        """
        Test that a sharing access token for a dashboard cannot be used to access insights
        that are not part of that dashboard.
        """
        # Create a dashboard with one insight
        insight_on_dashboard = Insight.objects.create(
            name="Insight on Dashboard",
            team=self.team,
            created_by=self.user,
            query={
                "kind": "TrendsQuery",
                "series": [{"event": "test_event"}],
            },
        )

        # Create a separate insight NOT on the dashboard
        insight_not_on_dashboard = Insight.objects.create(
            name="Insight NOT on Dashboard",
            team=self.team,
            created_by=self.user,
            query={
                "kind": "TrendsQuery",
                "series": [{"event": "secret_event"}],
            },
        )

        # Add only the first insight to the dashboard
        self.dashboard.tiles.create(
            insight=insight_on_dashboard,
            layouts={"sm": {"w": 6, "h": 5, "x": 0, "y": 0, "minW": 3, "minH": 3}},
        )

        # Create sharing configuration (simple access token approach)
        sharing_config = SharingConfiguration.objects.create(
            team=self.team, dashboard=self.dashboard, enabled=True, access_token="63P8B2SpeWtFSonTU8Kf3-0MrO5j1w"
        )

        # Test 1: Should be able to access insight that IS on the dashboard
        response = self.client.get(
            f"/api/environments/{self.team.id}/insights/{insight_on_dashboard.id}/",
            {"sharing_access_token": sharing_config.access_token},  # type: ignore[arg-type]
        )
        assert (
            response.status_code == 200
        ), f"Should be able to access insight on dashboard. Got {response.status_code}: {response.content}"

        # Test 2: Should NOT be able to access insight that is NOT on the dashboard
        response = self.client.get(
            f"/api/environments/{self.team.id}/insights/{insight_not_on_dashboard.id}/",
            {"sharing_access_token": sharing_config.access_token},  # type: ignore[arg-type]
        )
        assert response.status_code in [
            403,
            404,
        ], f"Should NOT be able to access insight not on dashboard. Got {response.status_code}: {response.content}"

    def test_sharing_access_token_cannot_override_filters(self):
        """
        Test that filters_override parameters are ignored when using sharing access tokens
        (they should only work for authenticated users).
        """
        # Create an insight on the dashboard
        insight = Insight.objects.create(
            name="Test Insight",
            team=self.team,
            created_by=self.user,
            query={
                "kind": "TrendsQuery",
                "series": [{"event": "original_event"}],
                "dateRange": {"date_from": "-7d"},
            },
        )

        self.dashboard.tiles.create(
            insight=insight,
            layouts={"sm": {"w": 6, "h": 5, "x": 0, "y": 0, "minW": 3, "minH": 3}},
        )

        # Create sharing configuration (simple access token approach)
        sharing_config = SharingConfiguration.objects.create(
            team=self.team, dashboard=self.dashboard, enabled=True, access_token="63P8B2SpeWtFSonTU8Kf3-0MrO5j1w"
        )

        # Test that filters_override is ignored when using sharing access token
        malicious_filters = {
            "date_from": "-365d",  # Try to access more data than originally configured
        }

        response = self.client.get(
            f"/api/environments/{self.team.id}/insights/{insight.id}/",
            {
                "sharing_access_token": sharing_config.access_token,
                "filters_override": json.dumps(malicious_filters),
                "from_dashboard": self.dashboard.id,
            },  # type: ignore[arg-type]
        )

        assert response.status_code == 200
        # The response should contain the original query, not the overridden one
        response_data = response.json()
        original_query = response_data.get("query", {})
        assert original_query.get("series", [{}])[0].get("event") == "original_event"

        # CRITICAL: This is the vulnerability - the date range should NOT be overridden to -365d
        # It should remain the original -7d from the insight definition
        date_from = original_query.get("dateRange", {}).get("date_from")
        assert (
            date_from == "-7d"
        ), f"SECURITY VULNERABILITY: filters_override was applied! Expected '-7d' but got '{date_from}'"

    def test_sharing_access_token_cannot_override_variables(self):
        """
        Test that variables_override parameter is ignored when using sharing access tokens.
        Variables only work in HogQL queries, not TrendsQuery.
        """
        from posthog.models.insight_variable import InsightVariable

        # Create an insight variable first
        variable = InsightVariable.objects.create(
            team=self.team, name="Test Event Variable", code_name="test_event", type="String", default_value="pageview"
        )

        # Create an insight that uses HogQL with a variable
        insight = Insight.objects.create(
            name="Test HogQL Insight with Variable",
            team=self.team,
            created_by=self.user,
            query={
                "kind": "DataVisualizationNode",
                "source": {
                    "kind": "HogQLQuery",
                    "query": "SELECT event, count() FROM events WHERE event = {variables.test_event} GROUP BY event",
                    "variables": {
                        str(variable.id): {
                            "code_name": variable.code_name,
                            "variableId": str(variable.id),
                            "value": variable.default_value,
                        }
                    },
                },
            },
        )

        self.dashboard.tiles.create(
            insight=insight,
            layouts={"sm": {"w": 6, "h": 5, "x": 0, "y": 0, "minW": 3, "minH": 3}},
        )

        # Create sharing configuration (simple access token approach)
        sharing_config = SharingConfiguration.objects.create(
            team=self.team, dashboard=self.dashboard, enabled=True, access_token="63P8B2SpeWtFSonTU8Kf3-0MrO5j1w"
        )

        # Try to override variables maliciously using proper format
        malicious_variables = {
            str(variable.id): {
                "code_name": variable.code_name,
                "variableId": str(variable.id),
                "value": "any_event",  # Try to access different events than intended
            }
        }

        response = self.client.get(
            f"/api/environments/{self.team.id}/insights/{insight.id}/",
            {
                "sharing_access_token": sharing_config.access_token,
                "variables_override": json.dumps(malicious_variables),
                "from_dashboard": self.dashboard.id,
            },  # type: ignore[arg-type]
        )

        assert response.status_code == 200
        # Variables should not be overridden in shared contexts
        response_data = response.json()
        original_query = response_data.get("query", {})
        source_query = original_query.get("source", {}).get("query")

        # The query should still contain the variable placeholder, not the overridden value
        assert (
            "{variables.test_event}" in source_query
        ), f"SECURITY VULNERABILITY: variables_override was applied! Query: {source_query}"

        # The variables should still contain the original default value, not the malicious override
        variables = original_query.get("source", {}).get("variables", {})
        actual_variable_value = variables.get(str(variable.id), {}).get("value")
        assert (
            actual_variable_value == "pageview"
        ), f"SECURITY VULNERABILITY: variables_override was applied! Expected 'pageview' but got '{actual_variable_value}'"

    def test_sharing_access_token_cannot_access_other_team_insights(self):
        """
        Test that sharing access tokens are properly scoped to the team and cannot access
        insights from other teams.
        """
        # Create another team
        other_team = self.create_team_with_organization(organization=self.organization)

        # Create an insight on the other team
        other_insight = Insight.objects.create(
            name="Other Team Insight",
            team=other_team,
            created_by=self.user,
            query={
                "kind": "TrendsQuery",
                "series": [{"event": "other_team_event"}],
            },
        )

        # Create sharing configuration for our team's dashboard
        sharing_config = SharingConfiguration.objects.create(
            team=self.team, dashboard=self.dashboard, enabled=True, access_token="63P8B2SpeWtFSonTU8Kf3-0MrO5j1w"
        )

        # Try to access the other team's insight - should fail
        response = self.client.get(
            f"/api/environments/{other_team.id}/insights/{other_insight.id}/",
            {"sharing_access_token": sharing_config.access_token},  # type: ignore[arg-type]
        )

        # Should be forbidden or not found - definitely not 200
        assert response.status_code in [
            403,
            404,
        ], f"Should not be able to access other team's insight. Got {response.status_code}: {response.content}"

    def test_sharing_access_token_list_insights_only_returns_dashboard_insights(self):
        """
        Test that when listing insights with sharing access token, only insights on the shared dashboard are returned.
        """
        # Create insights - some on dashboard, some not
        insight_on_dashboard = Insight.objects.create(
            name="On Dashboard",
            team=self.team,
            created_by=self.user,
            query={"kind": "TrendsQuery", "series": [{"event": "dashboard_event"}]},
        )

        insight_not_on_dashboard = Insight.objects.create(
            name="Not on Dashboard",
            team=self.team,
            created_by=self.user,
            query={"kind": "TrendsQuery", "series": [{"event": "secret_event"}]},
        )

        # Add only one to the dashboard
        self.dashboard.tiles.create(
            insight=insight_on_dashboard,
            layouts={"sm": {"w": 6, "h": 5, "x": 0, "y": 0, "minW": 3, "minH": 3}},
        )

        # Create sharing configuration
        sharing_config = SharingConfiguration.objects.create(
            team=self.team, dashboard=self.dashboard, enabled=True, access_token="63P8B2SpeWtFSonTU8Kf3-0MrO5j1w"
        )

        # List insights using sharing access token
        response = self.client.get(
            f"/api/environments/{self.team.id}/insights/",
            {"sharing_access_token": sharing_config.access_token},  # type: ignore[arg-type]
        )

        assert response.status_code == 200
        insights = response.json()["results"]

        # Should only return insights that are on the shared dashboard
        insight_ids = [insight["id"] for insight in insights]
        assert insight_on_dashboard.id in insight_ids, "Should include insight that's on the dashboard"
        assert insight_not_on_dashboard.id not in insight_ids, "Should NOT include insight that's not on the dashboard"

    def test_sharing_access_token_cannot_be_used_for_non_get_requests(self):
        """
        Test that sharing access tokens cannot be used for POST/PUT/DELETE requests
        (only GET requests are allowed per the authentication class).
        """
        # Already logged out in setUp()

        # Create sharing configuration
        sharing_config = SharingConfiguration.objects.create(
            team=self.team, dashboard=self.dashboard, enabled=True, access_token="63P8B2SpeWtFSonTU8Kf3-0MrO5j1w"
        )

        # Test 1: Try to create an insight using sharing access token as query param - should fail
        response = self.client.post(
            f"/api/environments/{self.team.id}/insights/?sharing_access_token={sharing_config.access_token}",
            {
                "name": "Malicious Insight",
                "query": {"kind": "TrendsQuery", "series": [{"event": "malicious_event"}]},
            },
        )
        assert (
            response.status_code in [401, 403]
        ), f"Should not be able to create insights with sharing access token in query params. Got {response.status_code}: {response.content}"

        # Test 2: Try to create an insight using sharing access token in body - should fail
        response = self.client.post(
            f"/api/environments/{self.team.id}/insights/",
            {
                "name": "Malicious Insight",
                "query": {"kind": "TrendsQuery", "series": [{"event": "malicious_event"}]},
                "sharing_access_token": sharing_config.access_token,
            },
        )
        assert (
            response.status_code in [401, 403]
        ), f"Should not be able to create insights with sharing access token in body. Got {response.status_code}: {response.content}"

        # Test 3: Try to update the dashboard using sharing access token as query param - should fail
        response = self.client.patch(
            f"/api/projects/{self.team.id}/dashboards/{self.dashboard.id}/?sharing_access_token={sharing_config.access_token}",
            {"name": "Hacked Dashboard"},
        )
        assert (
            response.status_code in [401, 403]
        ), f"Should not be able to update dashboard with sharing access token in query params. Got {response.status_code}: {response.content}"

        # Test 4: Try to update the dashboard using sharing access token in body - should fail
        response = self.client.patch(
            f"/api/projects/{self.team.id}/dashboards/{self.dashboard.id}/",
            {"name": "Hacked Dashboard", "sharing_access_token": sharing_config.access_token},
        )
        assert (
            response.status_code in [401, 403]
        ), f"Should not be able to update dashboard with sharing access token in body. Got {response.status_code}: {response.content}"
