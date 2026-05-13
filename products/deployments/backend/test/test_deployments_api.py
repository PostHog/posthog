from posthog.test.base import APIBaseTest

from rest_framework import status


class TestDeploymentsAPI(APIBaseTest):
    def test_list_returns_empty_for_authenticated_user(self) -> None:
        response = self.client.get(f"/api/projects/{self.team.id}/deployments/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertEqual(body["results"], [])
