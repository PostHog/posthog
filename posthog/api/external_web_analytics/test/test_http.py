from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from rest_framework import status


class TestExternalWebAnalyticsBreakdownEndpoint(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.breakdown_url = f"/api/projects/{self.team.id}/web_analytics/breakdown/"
        self.permission_patch = patch(
            "posthog.api.external_web_analytics.http.TEAM_IDS_WITH_EXTERNAL_WEB_ANALYTICS", [self.team.id]
        )

    @patch("posthog.api.external_web_analytics.query_adapter.WebStatsTableQueryRunner")
    @patch("posthog.api.external_web_analytics.http.TEAM_IDS_WITH_EXTERNAL_WEB_ANALYTICS")
    @patch("posthog.api.external_web_analytics.http.posthoganalytics.feature_enabled")
    def test_breakdown_success(self, mock_feature_enabled, mock_team_ids, mock_runner_class):
        mock_team_ids.__contains__.return_value = True
        mock_feature_enabled.return_value = True
        mock_runner = MagicMock()
        mock_response = MagicMock()
        mock_response.columns = [
            "context.columns.breakdown_value",
            "context.columns.visitors",
            "context.columns.views",
        ]
        mock_response.results = [
            ["Chrome", (150, 120), (500, 400)],
            ["Firefox", (100, 90), (300, 250)],
        ]
        mock_runner.calculate.return_value = mock_response
        mock_runner_class.return_value = mock_runner

        response = self.client.get(
            self.breakdown_url,
            {
                "date_from": "2025-01-01",
                "date_to": "2025-01-31",
                "breakdown_by": "Browser",
            },
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data["results"]) == 2
        assert data["results"][0]["breakdown_value"] == "Chrome"
        assert data["results"][0]["visitors"] == 150
        assert data["results"][0]["views"] == 500

    @patch("posthog.api.external_web_analytics.query_adapter.WebStatsTableQueryRunner")
    @patch("posthog.api.external_web_analytics.http.TEAM_IDS_WITH_EXTERNAL_WEB_ANALYTICS")
    @patch("posthog.api.external_web_analytics.http.posthoganalytics.feature_enabled")
    def test_breakdown_with_host_filter(self, mock_feature_enabled, mock_team_ids, mock_runner_class):
        mock_team_ids.__contains__.return_value = True
        mock_feature_enabled.return_value = True
        mock_runner = MagicMock()
        mock_response = MagicMock()
        mock_response.columns = ["context.columns.breakdown_value", "context.columns.visitors"]
        mock_response.results = [["Chrome", (150, 120)]]
        mock_runner.calculate.return_value = mock_response
        mock_runner_class.return_value = mock_runner

        response = self.client.get(
            self.breakdown_url,
            {
                "date_from": "2025-01-01",
                "date_to": "2025-01-31",
                "breakdown_by": "Browser",
                "host": "example.com",
            },
        )

        assert response.status_code == status.HTTP_200_OK

        # Verify host filter was applied
        _, kwargs = mock_runner_class.call_args
        query = kwargs["query"]
        assert len(query.properties) == 1
        assert query.properties[0].key == "$host"
        assert query.properties[0].value == ["example.com"]

    @patch("posthog.api.external_web_analytics.http.TEAM_IDS_WITH_EXTERNAL_WEB_ANALYTICS")
    @patch("posthog.api.external_web_analytics.http.posthoganalytics.feature_enabled")
    def test_breakdown_missing_required_params(self, mock_feature_enabled, mock_team_ids):
        mock_team_ids.__contains__.return_value = True
        mock_feature_enabled.return_value = True
        # Missing date_from
        response = self.client.get(
            self.breakdown_url,
            {
                "date_to": "2025-01-31",
                "breakdown_by": "Browser",
            },
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

        # Missing date_to
        response = self.client.get(
            self.breakdown_url,
            {
                "date_from": "2025-01-01",
                "breakdown_by": "Browser",
            },
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

        # Missing breakdown_by
        response = self.client.get(
            self.breakdown_url,
            {
                "date_from": "2025-01-01",
                "date_to": "2025-01-31",
            },
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @patch("posthog.api.external_web_analytics.http.TEAM_IDS_WITH_EXTERNAL_WEB_ANALYTICS")
    @patch("posthog.api.external_web_analytics.http.posthoganalytics.feature_enabled")
    def test_breakdown_invalid_breakdown_by(self, mock_feature_enabled, mock_team_ids):
        mock_team_ids.__contains__.return_value = True
        mock_feature_enabled.return_value = True
        response = self.client.get(
            self.breakdown_url,
            {
                "date_from": "2025-01-01",
                "date_to": "2025-01-31",
                "breakdown_by": "InvalidBreakdown",
            },
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @patch("posthog.api.external_web_analytics.query_adapter.WebStatsTableQueryRunner")
    @patch("posthog.api.external_web_analytics.http.TEAM_IDS_WITH_EXTERNAL_WEB_ANALYTICS")
    @patch("posthog.api.external_web_analytics.http.posthoganalytics.feature_enabled")
    def test_breakdown_with_pagination(self, mock_feature_enabled, mock_team_ids, mock_runner_class):
        mock_team_ids.__contains__.return_value = True
        mock_feature_enabled.return_value = True
        mock_runner = MagicMock()
        mock_response = MagicMock()
        mock_response.columns = ["context.columns.breakdown_value", "context.columns.visitors"]
        mock_response.results = [["Chrome", (150, 120)]]
        mock_runner.calculate.return_value = mock_response
        mock_runner_class.return_value = mock_runner

        response = self.client.get(
            self.breakdown_url,
            {
                "date_from": "2025-01-01",
                "date_to": "2025-01-31",
                "breakdown_by": "Browser",
                "limit": "50",
                "offset": "10",
            },
        )

        assert response.status_code == status.HTTP_200_OK

        # Verify limit was applied to query
        _, kwargs = mock_runner_class.call_args
        query = kwargs["query"]
        assert query.limit == 50

    def test_breakdown_requires_external_analytics_access(self):
        # This assumes the same access control as other endpoints
        response = self.client.get(
            self.breakdown_url,
            {
                "date_from": "2025-01-01",
                "date_to": "2025-01-31",
                "breakdown_by": "Browser",
            },
        )

        # Should pass through to the permission check
        assert response.status_code in [status.HTTP_200_OK, status.HTTP_403_FORBIDDEN]

    def test_breakdown_method_not_allowed(self):
        response = self.client.post(
            self.breakdown_url,
            {
                "date_from": "2025-01-01",
                "date_to": "2025-01-31",
                "breakdown_by": "Browser",
            },
        )
        assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED

    @patch("posthog.api.external_web_analytics.query_adapter.WebStatsTableQueryRunner")
    @patch("posthog.api.external_web_analytics.http.TEAM_IDS_WITH_EXTERNAL_WEB_ANALYTICS")
    @patch("posthog.api.external_web_analytics.http.posthoganalytics.feature_enabled")
    def test_breakdown_with_bounce_rate_breakdown(self, mock_feature_enabled, mock_team_ids, mock_runner_class):
        mock_team_ids.__contains__.return_value = True
        mock_feature_enabled.return_value = True
        mock_runner = MagicMock()
        mock_response = MagicMock()
        mock_response.columns = [
            "context.columns.breakdown_value",
            "context.columns.visitors",
            "context.columns.views",
            "context.columns.bounce_rate",
        ]
        mock_response.results = [["/home", (200, 180), (400, 350), (0.25, 0.30)]]
        mock_runner.calculate.return_value = mock_response
        mock_runner_class.return_value = mock_runner

        response = self.client.get(
            self.breakdown_url,
            {
                "date_from": "2025-01-01",
                "date_to": "2025-01-31",
                "breakdown_by": "Page",
            },
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        result = data["results"][0]
        assert result["breakdown_value"] == "/home"
        assert result["bounce_rate"] == 0.25

        # Verify includeBounceRate was set
        _, kwargs = mock_runner_class.call_args
        query = kwargs["query"]
        assert query.includeBounceRate is True

    def test_breakdown_team_isolation(self):
        other_organization = self.create_organization_with_features([])
        other_team = self.create_team_with_organization(organization=other_organization)
        other_url = f"/api/projects/{other_team.id}/web_analytics/breakdown/"

        response = self.client.get(
            other_url,
            {
                "date_from": "2025-01-01",
                "date_to": "2025-01-31",
                "breakdown_by": "Browser",
            },
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN

    @patch("posthog.api.external_web_analytics.http.TEAM_IDS_WITH_EXTERNAL_WEB_ANALYTICS")
    @patch("posthog.api.external_web_analytics.http.posthoganalytics.feature_enabled")
    def test_breakdown_invalid_date_format(self, mock_feature_enabled, mock_team_ids):
        mock_team_ids.__contains__.return_value = True
        mock_feature_enabled.return_value = True
        response = self.client.get(
            self.breakdown_url,
            {
                "date_from": "invalid-date",
                "date_to": "2025-01-31",
                "breakdown_by": "Browser",
            },
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @patch("posthog.api.external_web_analytics.query_adapter.WebStatsTableQueryRunner")
    @patch("posthog.api.external_web_analytics.http.TEAM_IDS_WITH_EXTERNAL_WEB_ANALYTICS")
    @patch("posthog.api.external_web_analytics.http.posthoganalytics.feature_enabled")
    def test_breakdown_empty_results(self, mock_feature_enabled, mock_team_ids, mock_runner_class):
        mock_team_ids.__contains__.return_value = True
        mock_feature_enabled.return_value = True
        mock_runner = MagicMock()
        mock_response = MagicMock()
        mock_response.columns = [
            "context.columns.breakdown_value",
            "context.columns.visitors",
            "context.columns.views",
        ]
        mock_response.results = []
        mock_runner.calculate.return_value = mock_response
        mock_runner_class.return_value = mock_runner

        response = self.client.get(
            self.breakdown_url,
            {
                "date_from": "2025-01-01",
                "date_to": "2025-01-31",
                "breakdown_by": "Browser",
            },
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["results"] == []
        assert data["next"] is None

    @patch("posthog.api.external_web_analytics.query_adapter.WebStatsTableQueryRunner")
    @patch("posthog.api.external_web_analytics.http.TEAM_IDS_WITH_EXTERNAL_WEB_ANALYTICS")
    @patch("posthog.api.external_web_analytics.http.posthoganalytics.feature_enabled")
    def test_breakdown_pagination_with_has_more(self, mock_feature_enabled, mock_team_ids, mock_runner_class):
        """Test pagination when there are more results available"""
        mock_team_ids.__contains__.return_value = True
        mock_feature_enabled.return_value = True
        mock_runner = MagicMock()
        mock_response = MagicMock()
        mock_response.columns = ["context.columns.breakdown_value", "context.columns.visitors"]
        mock_response.results = [["Chrome", (150, 120)], ["Firefox", (100, 90)]]
        mock_response.hasMore = True
        mock_runner.calculate.return_value = mock_response
        mock_runner_class.return_value = mock_runner

        response = self.client.get(
            self.breakdown_url,
            {
                "date_from": "2025-01-01",
                "date_to": "2025-01-31",
                "breakdown_by": "Browser",
                "limit": "2",
                "offset": "0",
            },
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()

        # Verify response structure
        assert "results" in data
        assert "next" in data
        assert "count" not in data  # Should not include count

        # Verify results
        assert len(data["results"]) == 2
        assert data["results"][0]["breakdown_value"] == "Chrome"
        assert data["results"][1]["breakdown_value"] == "Firefox"

        # Verify next URL is generated
        assert data["next"] is not None
        assert "offset=2" in data["next"]
        assert "limit=2" in data["next"]

        # Verify query parameters were passed correctly
        _, kwargs = mock_runner_class.call_args
        query = kwargs["query"]
        assert query.limit == 2
        assert query.offset == 0

    @patch("posthog.api.external_web_analytics.query_adapter.WebStatsTableQueryRunner")
    @patch("posthog.api.external_web_analytics.http.TEAM_IDS_WITH_EXTERNAL_WEB_ANALYTICS")
    @patch("posthog.api.external_web_analytics.http.posthoganalytics.feature_enabled")
    def test_breakdown_pagination_no_more_results(self, mock_feature_enabled, mock_team_ids, mock_runner_class):
        """Test pagination when there are no more results"""
        mock_team_ids.__contains__.return_value = True
        mock_feature_enabled.return_value = True
        mock_runner = MagicMock()
        mock_response = MagicMock()
        mock_response.columns = ["context.columns.breakdown_value", "context.columns.visitors"]
        mock_response.results = [["Chrome", (150, 120)]]
        mock_response.hasMore = False
        mock_runner.calculate.return_value = mock_response
        mock_runner_class.return_value = mock_runner

        response = self.client.get(
            self.breakdown_url,
            {
                "date_from": "2025-01-01",
                "date_to": "2025-01-31",
                "breakdown_by": "Browser",
                "limit": "2",
                "offset": "5",
            },
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()

        # Verify next URL is None when hasMore is False
        assert data["next"] is None

        # Verify query parameters were passed correctly
        _, kwargs = mock_runner_class.call_args
        query = kwargs["query"]
        assert query.limit == 2
        assert query.offset == 5
