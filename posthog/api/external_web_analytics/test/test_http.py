from unittest.mock import patch, MagicMock
from rest_framework import status
from posthog.test.base import APIBaseTest
import yaml


class ExternalWebAnalyticsAPITest(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.url = f"/api/projects/{self.team.id}/external_web_analytics/summary/"

    @patch("posthog.hogql_queries.web_analytics.external.summary_query_runner.chdb")
    def test_summary_success(self, mock_chdb):
        self.team.organization.is_platform = True
        self.team.organization.save()

        mock_chdb.query.side_effect = [
            "100,50,200\n",
            "25,50\n",
        ]

        response = self.client.post(
            self.url,
            data={
                "date_from": "2023-01-01",
                "date_to": "2023-01-31",
                "explicit_date": True,
            },
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["status"] == "success"
        assert data["data"]["unique_visitors"] == 100
        assert data["data"]["total_sessions"] == 50
        assert data["data"]["total_pageviews"] == 200
        assert data["data"]["bounce_rate"] == 0.5

    @patch("posthog.hogql_queries.web_analytics.external.summary_query_runner.chdb")
    def test_summary_success_explicit_date_default_false(self, mock_chdb):
        self.team.organization.is_platform = True
        self.team.organization.save()

        mock_chdb.query.side_effect = [
            "100,50,200\n",
            "25,50\n",
        ]

        response = self.client.post(
            self.url,
            data={
                "date_from": "2023-01-01",
                "date_to": "2023-01-31",
            },
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["status"] == "success"

    def test_summary_missing_date_params(self):
        response = self.client.post(self.url, data={})

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_summary_missing_date_from(self):
        response = self.client.post(
            self.url,
            data={
                "date_to": "2023-01-31",
                "explicit_date": True,
            },
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_summary_missing_date_to(self):
        response = self.client.post(
            self.url,
            data={
                "date_from": "2023-01-01",
                "explicit_date": False,
            },
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @patch("posthog.hogql_queries.web_analytics.external.summary_query_runner.chdb")
    def test_summary_platform_access_required(self, mock_chdb):
        self.team.organization.is_platform = False
        self.team.organization.save()

        response = self.client.post(
            self.url,
            data={
                "date_from": "2023-01-01",
                "date_to": "2023-01-31",
                "explicit_date": True,
            },
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["status"] == "error"
        assert data["error"]["code"] == "platform_access_required"
        assert mock_chdb.query.call_count == 0

    @patch("posthog.hogql_queries.web_analytics.external.summary_query_runner.chdb")
    def test_summary_query_execution_failed(self, mock_chdb):
        self.team.organization.is_platform = True
        self.team.organization.save()

        mock_chdb.query.side_effect = Exception("chdb connection failed")

        response = self.client.post(
            self.url,
            data={
                "date_from": "2023-01-01",
                "date_to": "2023-01-31",
                "explicit_date": False,
            },
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["status"] == "error"
        assert data["error"]["code"] == "query_execution_failed"

    @patch("posthog.hogql_queries.web_analytics.external.summary_query_runner.chdb")
    def test_summary_empty_results(self, mock_chdb):
        self.team.organization.is_platform = True
        self.team.organization.save()

        mock_chdb.query.side_effect = ["", ""]

        response = self.client.post(
            self.url,
            data={
                "date_from": "2023-01-01",
                "date_to": "2023-01-31",
                "explicit_date": True,
            },
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["status"] == "success"
        assert data["data"]["unique_visitors"] == 0
        assert data["data"]["total_sessions"] == 0
        assert data["data"]["total_pageviews"] == 0
        assert data["data"]["bounce_rate"] == 0.0

    def test_summary_requires_post(self):
        response = self.client.get(self.url)
        assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED

    def test_summary_team_isolation(self):
        other_organization = self.create_organization_with_features([])
        other_team = self.create_team_with_organization(organization=other_organization)
        other_url = f"/api/projects/{other_team.id}/external_web_analytics/summary/"

        response = self.client.post(
            other_url,
            data={
                "date_from": "2023-01-01",
                "date_to": "2023-01-31",
                "explicit_date": True,
            },
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_summary_included_in_openapi_schema(self):
        schema_response = self.client.get("/api/schema/")

        assert schema_response.status_code == 200
        assert schema_response.headers.get("Content-Type") == "application/vnd.oai.openapi; charset=utf-8"

        schema = yaml.safe_load(schema_response.content)

        paths = schema.get("paths", {})
        endpoint_path = f"/api/projects/{{project_id}}/external_web_analytics/summary/"

        assert endpoint_path in paths

    @patch("posthog.hogql_queries.web_analytics.external.summary_query_runner.chdb")
    def test_summary_sql_injection_protection(self, mock_chdb):
        self.team.organization.is_platform = True
        self.team.organization.save()

        mock_chdb.query.side_effect = [
            "100,50,200\n",
            "25,50\n",
        ]

        malicious_dates = [
            "2023-01-01'; DROP TABLE users; --",
            "2023-01-01' OR '1'='1",
            "2023-01-01'; SELECT * FROM sensitive_table; --",
            "2023-01-01' UNION SELECT password FROM users --",
            "'; DELETE FROM events; --",
        ]

        for malicious_date in malicious_dates:
            response = self.client.post(
                self.url,
                data={
                    "date_from": malicious_date,
                    "date_to": "2023-01-31",
                    "explicit_date": True,
                },
            )

            assert response.status_code in [status.HTTP_400_BAD_REQUEST, status.HTTP_200_OK]

            if response.status_code == status.HTTP_200_OK:
                for call in mock_chdb.query.call_args_list:
                    query_str = call[0][0] if call[0] else ""
                    assert "DROP TABLE" not in query_str.upper()
                    assert "DELETE FROM" not in query_str.upper()
                    assert "UNION SELECT" not in query_str.upper()
                    assert "SELECT * FROM" not in query_str.upper()

        mock_chdb.reset_mock()


class TestExternalWebAnalyticsBreakdownEndpoint(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.breakdown_url = f"/api/projects/{self.team.id}/external_web_analytics/breakdown/"
        self.permission_patch = patch(
            "posthog.api.external_web_analytics.http.TEAM_IDS_WITH_EXTERNAL_WEB_ANALYTICS", [self.team.id]
        )

    @patch("posthog.api.external_web_analytics.query_adapter.WebStatsTableQueryRunner")
    @patch("posthog.api.external_web_analytics.http.TEAM_IDS_WITH_EXTERNAL_WEB_ANALYTICS")
    def test_breakdown_success(self, mock_team_ids, mock_runner_class):
        mock_team_ids.__contains__.return_value = True
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
        assert data["count"] == 2
        assert len(data["results"]) == 2
        assert data["results"][0]["breakdown_value"] == "Chrome"
        assert data["results"][0]["visitors"] == 150
        assert data["results"][0]["views"] == 500

    @patch("posthog.api.external_web_analytics.query_adapter.WebStatsTableQueryRunner")
    @patch("posthog.api.external_web_analytics.http.TEAM_IDS_WITH_EXTERNAL_WEB_ANALYTICS")
    def test_breakdown_with_domain_filter(self, mock_team_ids, mock_runner_class):
        mock_team_ids.__contains__.return_value = True
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
                "domain": "example.com",
            },
        )

        assert response.status_code == status.HTTP_200_OK

        # Verify domain filter was applied
        _, kwargs = mock_runner_class.call_args
        query = kwargs["query"]
        assert len(query.properties) == 1
        assert query.properties[0].key == "$host"
        assert query.properties[0].value == ["example.com"]

    @patch("posthog.api.external_web_analytics.http.TEAM_IDS_WITH_EXTERNAL_WEB_ANALYTICS")
    def test_breakdown_missing_required_params(self, mock_team_ids):
        mock_team_ids.__contains__.return_value = True
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
    def test_breakdown_invalid_breakdown_by(self, mock_team_ids):
        mock_team_ids.__contains__.return_value = True
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
    def test_breakdown_with_metrics_filter(self, mock_team_ids, mock_runner_class):
        mock_team_ids.__contains__.return_value = True
        mock_runner = MagicMock()
        mock_response = MagicMock()
        mock_response.columns = [
            "context.columns.breakdown_value",
            "context.columns.visitors",
            "context.columns.views",
        ]
        mock_response.results = [["Chrome", (150, 120), (500, 400)]]
        mock_runner.calculate.return_value = mock_response
        mock_runner_class.return_value = mock_runner

        response = self.client.get(
            self.breakdown_url,
            {
                "date_from": "2025-01-01",
                "date_to": "2025-01-31",
                "breakdown_by": "Browser",
                "metrics": "visitors",
            },
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        result = data["results"][0]
        assert "breakdown_value" in result
        assert "visitors" in result
        assert "views" not in result

    @patch("posthog.api.external_web_analytics.query_adapter.WebStatsTableQueryRunner")
    @patch("posthog.api.external_web_analytics.http.TEAM_IDS_WITH_EXTERNAL_WEB_ANALYTICS")
    def test_breakdown_with_pagination(self, mock_team_ids, mock_runner_class):
        mock_team_ids.__contains__.return_value = True
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
    def test_breakdown_with_bounce_rate_breakdown(self, mock_team_ids, mock_runner_class):
        mock_team_ids.__contains__.return_value = True
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
        other_url = f"/api/projects/{other_team.id}/external_web_analytics/breakdown/"

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
    def test_breakdown_invalid_date_format(self, mock_team_ids):
        mock_team_ids.__contains__.return_value = True
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
    def test_breakdown_empty_results(self, mock_team_ids, mock_runner_class):
        mock_team_ids.__contains__.return_value = True
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
        assert data["count"] == 0
        assert data["results"] == []
