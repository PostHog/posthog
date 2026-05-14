import uuid

import pytest

from django.conf import settings as django_settings
from django.test.client import Client as HttpClient

from rest_framework import status

from posthog.api.oauth.test_dcr import generate_rsa_key
from posthog.models import OAuthApplication
from posthog.models.integration import Integration
from posthog.models.oauth import OAuthAccessToken, OAuthRefreshToken
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.team import Team
from posthog.models.user import User
from posthog.models.user_integration import UserIntegration
from posthog.redis import get_client
from posthog.temporal.oauth import ARRAY_APP_CLIENT_ID_DEV

VALID_SECRET = "posthog123"  # LOCAL_DEV_INTERNAL_API_SECRET; accepted under TEST mode
AUTH_HEADER = {"HTTP_X_INTERNAL_API_SECRET": VALID_SECRET}

# Module-level key so every test in this file shares the same OAUTH2_PROVIDER override.
_TEST_RSA_KEY = generate_rsa_key()


@pytest.fixture
def array_app(db, settings):
    """Provision the Array OAuth app the lookup endpoint mints tokens under.

    OAuthApplication.full_clean rejects RS256 unless OAUTH2_PROVIDER carries an
    RSA key, so we override the provider config for the test session.
    """
    settings.OAUTH2_PROVIDER = {**django_settings.OAUTH2_PROVIDER, "OIDC_RSA_PRIVATE_KEY": _TEST_RSA_KEY}
    app, _ = OAuthApplication.objects.get_or_create(
        client_id=ARRAY_APP_CLIENT_ID_DEV,
        defaults={
            "name": "Array Test App",
            "client_type": OAuthApplication.CLIENT_PUBLIC,
            "authorization_grant_type": OAuthApplication.GRANT_AUTHORIZATION_CODE,
            "redirect_uris": "https://app.posthog.com/callback",
            "algorithm": "RS256",
        },
    )
    yield app


@pytest.fixture(autouse=True)
def flush_token_cache():
    """Prevent cross-test bleed via the Redis token cache."""
    yield
    try:
        redis = get_client()
        for key in redis.scan_iter("posthog:internal_integration_lookup:*"):
            redis.delete(key)
    except Exception:
        pass


def _post(client: HttpClient, body: dict, **extra):
    return client.post(
        "/api/internal/integrations/lookup",
        data=body,
        content_type="application/json",
        **extra,
    )


def _fresh_scope() -> str:
    return f"test-scope-{uuid.uuid4()}"


class TestInternalIntegrationLookupTeam:
    @pytest.fixture(autouse=True)
    def setup_integration(self, db, array_app):
        self.organization = Organization.objects.create(name="Acme")
        self.team = Team.objects.create(organization=self.organization, name="Acme Prod")
        self.connector = User.objects.create_user(email="connector@acme.test", first_name="Conn", password="password")
        OrganizationMembership.objects.create(user=self.connector, organization=self.organization)
        self.integration = Integration.objects.create(
            team=self.team,
            kind="github",
            integration_id="12345678",
            config={"account": {"name": "acme-corp"}},
            sensitive_config={"access_token": "ghs_dummy"},
            created_by=self.connector,
        )

    def test_lookup_returns_team_match_with_tokens(self, client: HttpClient):
        response = _post(
            client,
            {"kind": "github", "integration_id": "12345678", "scope_id": _fresh_scope()},
            **AUTH_HEADER,
        )
        assert response.status_code == status.HTTP_200_OK, response.content
        body = response.json()
        assert body["source"] == "team"
        assert body["team_id"] == self.team.id
        assert body["organization_id"] == str(self.organization.id)
        assert body["integration_pk"] == str(self.integration.id)
        assert body["display_name"] == "acme-corp"
        assert body["access_token"] is not None
        assert body["refresh_token"] is not None
        assert body["expires_in"] is not None
        # Tokens were actually persisted and linked.
        access = OAuthAccessToken.objects.get(token=body["access_token"])
        refresh = OAuthRefreshToken.objects.get(token=body["refresh_token"])
        assert refresh.access_token_id == access.id
        assert access.user_id == self.connector.id
        assert access.scoped_teams == [self.team.id]

    def test_lookup_404_when_no_match(self, client: HttpClient):
        response = _post(
            client,
            {"kind": "github", "integration_id": "99999999", "scope_id": _fresh_scope()},
            **AUTH_HEADER,
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_lookup_rejects_unknown_kind(self, client: HttpClient):
        response = _post(
            client,
            {"kind": "not-a-real-kind", "integration_id": "x", "scope_id": _fresh_scope()},
            **AUTH_HEADER,
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_lookup_rejects_missing_integration_id(self, client: HttpClient):
        response = _post(client, {"kind": "github", "scope_id": _fresh_scope()}, **AUTH_HEADER)
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_lookup_rejects_missing_scope_id(self, client: HttpClient):
        response = _post(client, {"kind": "github", "integration_id": "12345678"}, **AUTH_HEADER)
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_lookup_requires_internal_secret(self, client: HttpClient):
        response = _post(client, {"kind": "github", "integration_id": "12345678", "scope_id": _fresh_scope()})
        assert response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)

    def test_lookup_rejects_wrong_secret(self, client: HttpClient):
        response = _post(
            client,
            {"kind": "github", "integration_id": "12345678", "scope_id": _fresh_scope()},
            HTTP_X_INTERNAL_API_SECRET="not-the-right-secret",
        )
        assert response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)


class TestInternalIntegrationLookupUser:
    @pytest.fixture(autouse=True)
    def setup_user_integration(self, db, array_app):
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
        response = _post(
            client,
            {"kind": "github", "integration_id": "55555555", "scope_id": _fresh_scope()},
            **AUTH_HEADER,
        )
        assert response.status_code == status.HTTP_200_OK, response.content
        body = response.json()
        assert body["source"] == "user"
        assert body["team_id"] == self.team.id
        assert body["organization_id"] == str(self.organization.id)
        assert body["integration_pk"] == str(self.user_integration.id)
        assert body["display_name"] == "alice-personal"
        assert body["user_id"] == self.user.id
        assert body["access_token"] is not None
        assert body["refresh_token"] is not None

    def test_team_match_wins_over_user_match(self, client: HttpClient):
        other_team = Team.objects.create(organization=self.organization, name="Other team")
        team_integration = Integration.objects.create(
            team=other_team,
            kind="github",
            integration_id="55555555",
            config={"account": {"name": "team-owned"}},
            sensitive_config={"access_token": "ghs_dummy"},
        )
        response = _post(
            client,
            {"kind": "github", "integration_id": "55555555", "scope_id": _fresh_scope()},
            **AUTH_HEADER,
        )
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["source"] == "team"
        assert body["team_id"] == other_team.id
        assert body["integration_pk"] == str(team_integration.id)

    def test_user_match_without_current_team_returns_404(self, client: HttpClient):
        self.user.current_team = None
        self.user.current_organization = None
        self.user.save(update_fields=["current_team", "current_organization"])
        response = _post(
            client,
            {"kind": "github", "integration_id": "55555555", "scope_id": _fresh_scope()},
            **AUTH_HEADER,
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND


class TestInternalIntegrationLookupCaching:
    @pytest.fixture(autouse=True)
    def setup_integration(self, db, array_app):
        self.organization = Organization.objects.create(name="Acme")
        self.team = Team.objects.create(organization=self.organization, name="Acme Prod")
        self.connector = User.objects.create_user(email="cache@acme.test", first_name="Cache", password="password")
        OrganizationMembership.objects.create(user=self.connector, organization=self.organization)
        self.integration = Integration.objects.create(
            team=self.team,
            kind="github",
            integration_id="cache-id",
            config={"account": {"name": "acme-corp"}},
            sensitive_config={},
            created_by=self.connector,
        )

    def test_same_scope_returns_cached_tokens(self, client: HttpClient):
        scope = _fresh_scope()
        body = {"kind": "github", "integration_id": "cache-id", "scope_id": scope}

        first = _post(client, body, **AUTH_HEADER).json()
        second = _post(client, body, **AUTH_HEADER).json()

        assert first["access_token"] == second["access_token"]
        assert first["refresh_token"] == second["refresh_token"]
        # And we only created one OAuth row, not two.
        assert OAuthAccessToken.objects.filter(token=first["access_token"]).count() == 1

    def test_different_scopes_mint_distinct_tokens(self, client: HttpClient):
        body_base = {"kind": "github", "integration_id": "cache-id"}
        first = _post(client, {**body_base, "scope_id": _fresh_scope()}, **AUTH_HEADER).json()
        second = _post(client, {**body_base, "scope_id": _fresh_scope()}, **AUTH_HEADER).json()
        assert first["access_token"] != second["access_token"]
        assert first["refresh_token"] != second["refresh_token"]
