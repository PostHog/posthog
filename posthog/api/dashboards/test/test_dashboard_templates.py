from unittest.mock import Mock, PropertyMock, patch

from rest_framework import status

from posthog.test.base import APIBaseTest


class TestDashboardTemplates(APIBaseTest):
    @patch("posthog.api.dashboards.dashboard_templates.requests.get")
    def test_repository_calls_to_github_and_returns_the_listing(self, patched_requests) -> None:
        mock_response = Mock()
        mock_response.status_code = 200
        mock_text = PropertyMock(return_value='{"a": "b"}')
        type(mock_response).text = mock_text
        patched_requests.return_value = mock_response

        response = self.client.get(f"/api/projects/{self.team.pk}/dashboard_templates/repository")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"a": "b"}
