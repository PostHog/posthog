import pytest

from django.test.client import Client as HttpClient

from rest_framework import status

from posthog.models.integration import Integration
from posthog.models.organization import Organization
from posthog.models.team import Team
from posthog.models.user import User
from posthog.models.user_integration import UserIntegration

VALID_SECRET = "posthog123"  # LOCAL_DEV_INTERNAL_API_SECRET; accepted under TEST mode
AUTH_HEADER = {"HTTP_X_INTERNAL_API_SECRET": VALID_SECRET}


def _post(client: HttpClient, body: dict, **extra):
    return client.post(
        "/api/internal/integrations/lookup",
        data=body,
        content_type="application/json",
        **extra,
    )


class TestInternalIntegrationLookupTeam:
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

    def test_lookup_returns_team_match(self, client: HttpClient):
        response = _post(client, {"kind": "github", "integration_id": "12345678"}, **AUTH_HEADER)
        assert response.status_code == status.HTTP_200_OK, response.content
        body = response.json()
        assert body["source"] == "team"
        assert body["team_id"] == self.team.id
        assert body["organization_id"] == str(self.organization.id)
        assert body["integration_pk"] == str(self.integration.id)
        assert body["display_name"] == "acme-corp"
        # No org members or created_by — nothing to mint under.
        assert body["personal_api_key"] is None
        assert set(body.keys()) == {
            "source",
            "team_id",
            "organization_id",
            "integration_pk",
            "display_name",
            "personal_api_key",
        }

    def test_lookup_404_when_no_match(self, client: HttpClient):
        response = _post(client, {"kind": "github", "integration_id": "99999999"}, **AUTH_HEADER)
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_lookup_rejects_unknown_kind(self, client: HttpClient):
        response = _post(client, {"kind": "not-a-real-kind", "integration_id": "x"}, **AUTH_HEADER)
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_lookup_rejects_missing_integration_id(self, client: HttpClient):
        response = _post(client, {"kind": "github"}, **AUTH_HEADER)
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_lookup_requires_internal_secret(self, client: HttpClient):
        response = _post(client, {"kind": "github", "integration_id": "12345678"})
        assert response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)

    def test_lookup_rejects_wrong_secret(self, client: HttpClient):
        response = _post(
            client,
            {"kind": "github", "integration_id": "12345678"},
            HTTP_X_INTERNAL_API_SECRET="not-the-right-secret",
        )
        assert response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)


class TestInternalIntegrationLookupUser:
    @pytest.fixture(autouse=True)
    def setup_user_integration(self, db):
        self.organization = Organization.objects.create(name="Acme")
        self.team = Team.objects.create(organization=self.organization, name="Acme Prod")
        self.user = User.objects.create(
            email="alice@acme.com",
            current_team=self.team,
            current_organization=self.organization,
        )
        self.user_integration = UserIntegration.objects.create(
            user=self.user,
            kind="github",
            integration_id="55555555",
            config={"account": {"name": "alice-personal"}},
            sensitive_config={"access_token": "ghu_dummy"},
        )

    def test_lookup_returns_user_match_when_no_team_match(self, client: HttpClient):
        response = _post(client, {"kind": "github", "integration_id": "55555555"}, **AUTH_HEADER)
        assert response.status_code == status.HTTP_200_OK, response.content
        body = response.json()
        assert body["source"] == "user"
        assert body["team_id"] == self.team.id
        assert body["organization_id"] == str(self.organization.id)
        assert body["integration_pk"] == str(self.user_integration.id)
        assert body["display_name"] == "alice-personal"
        assert body["user_id"] == self.user.id
        # personal_api_key is present; value depends on whether the Array OAuth app exists in this test env.
        assert "personal_api_key" in body

    def test_team_match_wins_over_user_match(self, client: HttpClient):
        other_team = Team.objects.create(organization=self.organization, name="Other team")
        team_integration = Integration.objects.create(
            team=other_team,
            kind="github",
            integration_id="55555555",
            config={"account": {"name": "team-owned"}},
            sensitive_config={"access_token": "ghs_dummy"},
        )
        response = _post(client, {"kind": "github", "integration_id": "55555555"}, **AUTH_HEADER)
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["source"] == "team"
        assert body["team_id"] == other_team.id
        assert body["integration_pk"] == str(team_integration.id)

    def test_user_match_without_current_team_returns_404(self, client: HttpClient):
        self.user.current_team = None
        self.user.current_organization = None
        self.user.save(update_fields=["current_team", "current_organization"])
        response = _post(client, {"kind": "github", "integration_id": "55555555"}, **AUTH_HEADER)
        assert response.status_code == status.HTTP_404_NOT_FOUND
