from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from posthog.models.utils import uuid7


class TestDeploymentsAPI(APIBaseTest):
    @parameterized.expand(
        [
            ("flag on returns empty list", True, status.HTTP_200_OK),
            ("flag off returns 403", False, status.HTTP_403_FORBIDDEN),
        ]
    )
    def test_list_respects_feature_flag(self, _name: str, flag_enabled: bool, expected_status: int) -> None:
        with patch(
            "products.deployments.backend.access.posthoganalytics.feature_enabled",
            return_value=flag_enabled,
        ):
            response = self.client.get(f"/api/projects/{self.team.id}/deployments/")

        self.assertEqual(response.status_code, expected_status)
        if expected_status == status.HTTP_200_OK:
            self.assertEqual(response.json()["results"], [])

    @parameterized.expand(
        [
            ("redeploy",),
            ("rollback",),
            ("refresh-preview",),
        ]
    )
    @patch("products.deployments.backend.access.posthoganalytics.feature_enabled", return_value=True)
    def test_stub_action_returns_501_when_flag_on(self, action: str, _mock_flag: object) -> None:
        # The stubs never call get_object, so the deployment id only has to be a
        # syntactically valid UUID — no row needs to exist for the URL to route.
        response = self.client.post(f"/api/projects/{self.team.id}/deployments/{uuid7()}/{action}/")

        self.assertEqual(response.status_code, status.HTTP_501_NOT_IMPLEMENTED)
