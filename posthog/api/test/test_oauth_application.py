import pytest
from posthog.test.base import APIBaseTest

from rest_framework import status
from rest_framework.test import APIClient

from posthog.models.oauth import OAuthApplication


@pytest.mark.requires_secrets
class TestOAuthApplicationMetadataView(APIBaseTest):
    public_fields = ["name", "client_id"]

    def setUp(self):
        super().setUp()

        self.application = OAuthApplication.objects.create(
            name="Test App",
            client_id="client_id",
            client_secret="client_secret",
            redirect_uris="https://example.com/callback",
            user=self.user,
            organization=self.organization,
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            algorithm="RS256",
        )

    def test_get_application_metadata_success(self):
        url = f"/api/oauth_application/metadata/{self.application.client_id}/"
        response = self.client.get(url)

        assert response.status_code == status.HTTP_200_OK
        expected_data = {"name": "Test App", "client_id": self.application.client_id}
        assert response.data == expected_data

    def test_get_application_metadata_only_exposes_public_fields(self):
        url = f"/api/oauth_application/metadata/{self.application.client_id}/"
        response = self.client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data.keys()) == len(self.public_fields)
        assert response.data["name"] == self.application.name
        assert response.data["client_id"] == self.application.client_id

        assert "client_secret" not in response.data
        assert "redirect_uris" not in response.data
        assert "id" not in response.data
        assert "skip_authorization" not in response.data

    def test_get_application_metadata_not_found(self):
        url = f"/api/oauth_application/metadata/non_existent_client_id/"
        response = self.client.get(url)

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert "detail" in response.data
        assert response.data["detail"] == "Not found."

    def test_endpoint_is_publicly_accessible_even_if_client_is_authenticated(self):
        url = f"/api/oauth_application/metadata/{self.application.client_id}/"
        response = self.client.get(url)

        assert response.status_code == status.HTTP_200_OK
        expected_data = {"name": "Test App", "client_id": self.application.client_id}
        assert response.data == expected_data

    def test_endpoint_is_publicly_accessible_with_unauthenticated_client(self):
        unauthenticated_client = APIClient()

        url = f"/api/oauth_application/metadata/{self.application.client_id}/"
        response = unauthenticated_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        expected_data = {"name": "Test App", "client_id": self.application.client_id}
        assert response.data == expected_data
