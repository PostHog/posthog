from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from posthog.api.test.dashboards import DashboardAPI

MOCK_PATH = "posthog.api.dashboard_metadata.hit_openai"


class TestGenerateDashboardMetadata(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()
        self.dashboard_api = DashboardAPI(self.client, self.team, self.assertEqual)

    def _url(self, dashboard_id: int) -> str:
        return f"/api/projects/{self.team.id}/dashboards/{dashboard_id}/generate_metadata/"

    @patch(MOCK_PATH)
    def test_returns_name_and_description(self, mock_openai):
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "d"})
        _, _ = self.dashboard_api.create_insight({"dashboards": [dashboard_id], "name": "Pageviews"})
        mock_openai.return_value = ('{"name": "Traffic overview", "description": "Key traffic metrics."}', 10, 20)
        response = self.client.post(self._url(dashboard_id), {}, format="json")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["name"] == "Traffic overview"
        assert response.json()["description"] == "Key traffic metrics."

    @parameterized.expand(
        [
            ("no_tiles",),
            ("button_tiles_only",),
        ]
    )
    @patch(MOCK_PATH)
    def test_returns_400_when_no_insight_or_text_tiles(self, _case_name, mock_openai):
        if _case_name == "no_tiles":
            dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "Empty"})
        else:
            dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "d"})
            _, _ = self.dashboard_api.create_button_tile(dashboard_id)
        response = self.client.post(self._url(dashboard_id), {}, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        err = response.json()["error"].lower()
        assert "insight" in err or "text" in err
        mock_openai.assert_not_called()

    @patch(MOCK_PATH, side_effect=Exception("LLM API error"))
    def test_llm_failure_returns_500(self, mock_openai):
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "d"})
        _, _ = self.dashboard_api.create_insight({"dashboards": [dashboard_id], "name": "Pageviews"})
        response = self.client.post(self._url(dashboard_id), {}, format="json")

        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert "Failed" in response.json()["error"]

    def test_ai_not_approved_returns_403(self):
        self.organization.is_ai_data_processing_approved = False
        self.organization.save()
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "d"})
        _, _ = self.dashboard_api.create_insight({"dashboards": [dashboard_id], "name": "Pageviews"})
        response = self.client.post(self._url(dashboard_id), {}, format="json")

        assert response.status_code == status.HTTP_403_FORBIDDEN
