from posthog.test.base import APIBaseTest

from rest_framework import status

from unittest.mock import patch


class TestDeploymentsAPI(APIBaseTest):
    @patch("products.deployments.backend.access.posthoganalytics.feature_enabled", return_value=True)
    def test_list_returns_empty_for_authenticated_user_with_flag_on(self, _mock_flag: object) -> None:
        response = self.client.get(f"/api/projects/{self.team.id}/deployments/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertEqual(body["results"], [])

    @patch("products.deployments.backend.access.posthoganalytics.feature_enabled", return_value=False)
    def test_list_returns_403_when_flag_off(self, _mock_flag: object) -> None:
        response = self.client.get(f"/api/projects/{self.team.id}/deployments/")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
