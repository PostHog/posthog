import json

from unittest.mock import MagicMock, _patch, patch

from parameterized import parameterized
from rest_framework import status

from posthog.models.integration import Integration

from ee.api.vercel.test.base import VercelTestBase


class TestVercelResourceAPI(VercelTestBase):
    client_id_patcher: _patch
    jwks_patcher: _patch
    mock_get_jwks: MagicMock

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.client_id_patcher = patch("ee.settings.VERCEL_CLIENT_INTEGRATION_ID", "test_audience")
        cls.jwks_patcher = patch("ee.api.authentication.get_vercel_jwks")
        cls.client_id_patcher.start()
        cls.mock_get_jwks = cls.jwks_patcher.start()

    @classmethod
    def tearDownClass(cls):
        cls.client_id_patcher.stop()
        cls.jwks_patcher.stop()
        super().tearDownClass()

    def setUp(self):
        super().setUp()
        self.resource = Integration.objects.create(
            team=self.team,
            kind=Integration.IntegrationKind.VERCEL,
            integration_id=str(self.team.pk),
            config={
                "productId": "posthog",
                "name": "Test Resource",
                "metadata": {"test": "data"},
                "billingPlanId": "free",
            },
            created_by=self.user,
        )
        self.resource_id = str(self.resource.pk)
        self.base_url = f"/api/vercel/v1/installations/{self.installation_id}/resources"
        self.resource_url = f"{self.base_url}/{self.resource_id}/"
        self.mock_get_jwks.return_value = self.mock_jwks

    def _request(self, method, url=None, data=None, auth_type="user", **kwargs):
        headers = self._get_auth_headers(auth_type)
        url = url or self.resource_url
        if data:
            kwargs.update(content_type="application/json", data=json.dumps(data))
        return getattr(self.client, method)(url, **headers, **kwargs)

    @patch("ee.vercel.integration.VercelIntegration.create_resource")
    def test_create_calls_create_resource(self, mock_create):
        payload = {
            "productId": "posthog",
            "name": "New Resource",
            "metadata": {"key": "value"},
            "billingPlanId": "free",
        }
        mock_create.return_value = {
            "id": "new_resource_id",
            "productId": "posthog",
            "name": "New Resource",
            "metadata": {"key": "value"},
            "status": "ready",
            "secrets": [],
            "billingPlan": {"id": "free"},
        }

        response = self._request("post", url=f"{self.base_url}/", data=payload)

        assert response.status_code == status.HTTP_200_OK
        mock_create.assert_called_once_with(self.installation_id, payload)
        assert response.json() == mock_create.return_value

    @patch("ee.vercel.integration.VercelIntegration.get_resource")
    def test_retrieve_calls_get_resource(self, mock_get):
        mock_get.return_value = {
            "id": self.resource_id,
            "productId": "posthog",
            "name": "Test Resource",
            "metadata": {"test": "data"},
            "status": "ready",
            "secrets": [],
            "billingPlan": {"id": "free"},
        }

        response = self._request("get", auth_type="system")

        assert response.status_code == status.HTTP_200_OK
        mock_get.assert_called_once_with(self.resource_id, self.installation_id)
        assert response.json() == mock_get.return_value

    @patch("ee.vercel.integration.VercelIntegration.update_resource")
    def test_partial_update_calls_update_resource(self, mock_update):
        payload = {
            "name": "Updated Resource",
            "metadata": {"updated": "true"},
        }
        mock_update.return_value = {
            "id": self.resource_id,
            "productId": "posthog",
            "name": "Updated Resource",
            "metadata": {"updated": "true"},
            "status": "ready",
            "secrets": [],
            "billingPlan": {"id": "free"},
        }

        response = self._request("patch", data=payload)

        assert response.status_code == status.HTTP_200_OK
        mock_update.assert_called_once_with(self.resource_id, self.installation_id, payload)
        assert response.json() == mock_update.return_value

    @patch("ee.vercel.integration.VercelIntegration.delete_resource")
    def test_destroy_calls_delete_resource(self, mock_delete):
        response = self._request("delete")

        assert response.status_code == status.HTTP_204_NO_CONTENT
        mock_delete.assert_called_once_with(self.resource_id)

    @parameterized.expand(
        [
            (
                "create",
                "post",
                "/api/vercel/v1/installations//resources/",
                {"productId": "posthog", "name": "Test", "metadata": {}, "billingPlanId": "free"},
            ),
            ("retrieve", "get", "/api/vercel/v1/installations//resources/123/", None),
            ("update", "patch", "/api/vercel/v1/installations//resources/123/", {"name": "Updated"}),
        ]
    )
    def test_missing_installation_id(self, name, method, url, data):
        response = self._request(method, url=url, data=data, auth_type="system" if method == "get" else "user")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    @parameterized.expand(
        [
            ("retrieve", "get", "system"),
            ("update", "patch", "user"),
            ("delete", "delete", "user"),
        ]
    )
    def test_missing_resource_id(self, name, method, auth_type):
        url = f"{self.base_url}//"
        data = {"name": "Updated"} if method == "patch" else None
        response = self._request(method, url=url, data=data, auth_type=auth_type)
        assert response.status_code == status.HTTP_404_NOT_FOUND

    @patch("ee.vercel.integration.VercelIntegration.get_resource")
    def test_retrieve_handles_resource_not_found(self, mock_get):
        from rest_framework.exceptions import NotFound

        mock_get.side_effect = NotFound("Resource not found")

        response = self._request("get", auth_type="system")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    @patch("ee.vercel.integration.VercelIntegration.create_resource")
    def test_create_handles_integration_errors(self, mock_create):
        from rest_framework.exceptions import ValidationError

        mock_create.side_effect = ValidationError("Integration error")

        payload = {
            "productId": "posthog",
            "name": "Test",
            "metadata": {},
            "billingPlanId": "free",
        }
        response = self._request("post", url=f"{self.base_url}/", data=payload)
        assert response.status_code == status.HTTP_400_BAD_REQUEST
