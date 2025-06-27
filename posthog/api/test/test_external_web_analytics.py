from unittest.mock import patch
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
