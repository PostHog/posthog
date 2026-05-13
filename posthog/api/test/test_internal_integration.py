import pytest

from django.test.client import Client as HttpClient

from rest_framework import status

from posthog.models.integration import Integration
from posthog.models.organization import Organization
from posthog.models.team import Team

VALID_SECRET = "posthog123"  # LOCAL_DEV_INTERNAL_API_SECRET; accepted under TEST mode
AUTH_HEADER = {"HTTP_X_INTERNAL_API_SECRET": VALID_SECRET}


class TestInternalIntegrationLookup:
    @pytest.fixture(autouse=True)
    def setup_integration(self, db):
        self.organization = Organization.objects.create(name="Acme")
        self.team = Team.objects.create(organization=self.organization, name="Acme Prod")
        self.integration = Integration.objects.create(
            team=self.team,
            kind="github",
            integration_id="12345678",
            config={"account": {"name": "acme-corp"}},
            sensitive_config={"access_token": "ghs_dummy"},
        )

    def _post(self, client: HttpClient, body: dict, **extra) -> "HttpClient.response":
        return client.post(
            "/api/internal/integrations/lookup",
            data=body,
            content_type="application/json",
            **extra,
        )

    def test_lookup_returns_team_and_org_for_matching_integration(self, client: HttpClient):
        response = self._post(client, {"kind": "github", "integration_id": "12345678"}, **AUTH_HEADER)
        assert response.status_code == status.HTTP_200_OK, response.content
        assert response.json() == {
            "team_id": self.team.id,
            "organization_id": str(self.organization.id),
            "integration_pk": self.integration.id,
            "display_name": "acme-corp",
        }

    def test_lookup_404_when_no_match(self, client: HttpClient):
        response = self._post(client, {"kind": "github", "integration_id": "99999999"}, **AUTH_HEADER)
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_lookup_rejects_unknown_kind(self, client: HttpClient):
        response = self._post(client, {"kind": "not-a-real-kind", "integration_id": "x"}, **AUTH_HEADER)
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_lookup_rejects_missing_integration_id(self, client: HttpClient):
        response = self._post(client, {"kind": "github"}, **AUTH_HEADER)
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_lookup_requires_internal_secret(self, client: HttpClient):
        response = self._post(client, {"kind": "github", "integration_id": "12345678"})
        assert response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)

    def test_lookup_rejects_wrong_secret(self, client: HttpClient):
        response = self._post(
            client,
            {"kind": "github", "integration_id": "12345678"},
            HTTP_X_INTERNAL_API_SECRET="not-the-right-secret",
        )
        assert response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)
