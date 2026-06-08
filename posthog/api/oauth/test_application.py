import pytest
from posthog.test.base import APIBaseTest

from parameterized import parameterized
from rest_framework import status
from rest_framework.test import APIClient

from posthog.models.oauth import OAuthApplication
from posthog.models.organization import Organization


@pytest.mark.requires_secrets
class TestOrganizationOAuthApplicationViewSet(APIBaseTest):
    expected_fields = {"id", "name", "client_id", "redirect_uris_list", "is_verified", "created", "updated"}

    def _create_app(self, organization, name="Test App", redirect_uris="https://example.com/callback", **kwargs):
        return OAuthApplication.objects.create(
            name=name,
            redirect_uris=redirect_uris,
            organization=organization,
            user=self.user,
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            algorithm="RS256",
            **kwargs,
        )

    def test_list_returns_apps_for_current_org(self):
        app = self._create_app(self.organization, name="My App")
        response = self.client.get("/api/organizations/@current/oauth_applications/")

        assert response.status_code == status.HTTP_200_OK
        assert response.data["count"] == 1
        assert response.data["results"][0]["id"] == str(app.id)
        assert response.data["results"][0]["name"] == "My App"

    def test_list_does_not_return_apps_from_other_org(self):
        other_org = Organization.objects.create(name="Other Org")
        self._create_app(self.organization, name="My App")
        self._create_app(other_org, name="Other App")

        response = self.client.get("/api/organizations/@current/oauth_applications/")

        assert response.status_code == status.HTTP_200_OK
        assert response.data["count"] == 1
        assert response.data["results"][0]["name"] == "My App"

    def test_list_returns_empty_when_no_apps(self):
        response = self.client.get("/api/organizations/@current/oauth_applications/")

        assert response.status_code == status.HTTP_200_OK
        assert response.data["count"] == 0
        assert response.data["results"] == []

    def test_response_contains_only_expected_fields(self):
        self._create_app(self.organization)
        response = self.client.get("/api/organizations/@current/oauth_applications/")

        assert response.status_code == status.HTTP_200_OK
        assert set(response.data["results"][0].keys()) == self.expected_fields

    @parameterized.expand(["client_secret", "redirect_uris", "skip_authorization", "algorithm", "user"])
    def test_sensitive_field_not_exposed(self, field_name):
        self._create_app(self.organization)
        response = self.client.get("/api/organizations/@current/oauth_applications/")

        assert response.status_code == status.HTTP_200_OK
        assert field_name not in response.data["results"][0]

    def test_redirect_uris_list_splits_space_separated_uris(self):
        self._create_app(self.organization, redirect_uris="https://a.com/cb https://b.com/cb")
        response = self.client.get("/api/organizations/@current/oauth_applications/")

        assert response.data["results"][0]["redirect_uris_list"] == ["https://a.com/cb", "https://b.com/cb"]

    def test_list_ordered_by_most_recent_first(self):
        app1 = self._create_app(self.organization, name="First")
        app2 = self._create_app(self.organization, name="Second")
        response = self.client.get("/api/organizations/@current/oauth_applications/")

        assert response.data["results"][0]["id"] == str(app2.id)
        assert response.data["results"][1]["id"] == str(app1.id)

    def test_unauthenticated_request_is_rejected(self):
        unauthenticated_client = APIClient()
        response = unauthenticated_client.get("/api/organizations/@current/oauth_applications/")

        assert response.status_code in [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN]

    def test_read_only_no_create(self):
        response = self.client.post(
            "/api/organizations/@current/oauth_applications/",
            {"name": "New App"},
        )
        assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED

    def test_read_only_no_detail_endpoint(self):
        app = self._create_app(self.organization)
        response = self.client.get(f"/api/organizations/@current/oauth_applications/{app.id}/")
        assert response.status_code == status.HTTP_404_NOT_FOUND
