import uuid
from datetime import timedelta

from freezegun import freeze_time
from posthog.test.base import APIBaseTest

from django.conf import settings
from django.test import override_settings
from django.utils import timezone

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from rest_framework import status
from rest_framework.test import APIClient

from posthog.models.oauth import OAuthAccessToken, OAuthApplication, OAuthGrant, OAuthRefreshToken
from posthog.models.user import User


def _generate_rsa_key() -> str:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return pem.decode("utf-8")


@freeze_time("2024-06-15T12:00:00Z")
@override_settings(
    OAUTH2_PROVIDER={
        **settings.OAUTH2_PROVIDER,
        "OIDC_RSA_PRIVATE_KEY": _generate_rsa_key(),
    }
)
class TestConnectedAppsViewSet(APIBaseTest):
    def _create_app(self, name: str = "Test App", **kwargs) -> OAuthApplication:
        return OAuthApplication.objects.create(
            name=name,
            redirect_uris="https://example.com/callback",
            organization=self.organization,
            user=self.user,
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            algorithm="RS256",
            **kwargs,
        )

    def _create_token(
        self,
        app: OAuthApplication,
        user: User | None = None,
        scope: str = "read write",
        expires_hours: int = 1,
    ) -> OAuthAccessToken:
        return OAuthAccessToken.objects.create(
            user=user or self.user,
            application=app,
            token=f"test-token-{OAuthAccessToken.objects.count()}",
            scope=scope,
            expires=timezone.now() + timedelta(hours=expires_hours),
        )

    def test_list_returns_apps_with_active_tokens(self):
        app = self._create_app("Claude Code", logo_uri="https://example.com/logo.png")
        self._create_token(app)

        response = self.client.get("/api/oauth/connected-apps/")

        assert response.status_code == status.HTTP_200_OK
        assert len(response.json()) == 1
        data = response.json()[0]
        assert data["id"] == str(app.id)
        assert data["name"] == "Claude Code"
        assert data["logo_uri"] == "https://example.com/logo.png"
        assert set(data["scopes"]) == {"read", "write"}
        assert "authorized_at" in data

    def test_list_excludes_expired_tokens(self):
        app = self._create_app()
        self._create_token(app, expires_hours=-1)

        response = self.client.get("/api/oauth/connected-apps/")

        assert response.status_code == status.HTTP_200_OK
        assert len(response.json()) == 0

    def test_list_excludes_other_users_tokens(self):
        other_user = User.objects.create_and_join(self.organization, "other@example.com", "password")
        app = self._create_app()
        self._create_token(app, user=other_user)

        response = self.client.get("/api/oauth/connected-apps/")

        assert response.status_code == status.HTTP_200_OK
        assert len(response.json()) == 0

    def test_list_groups_multiple_tokens_per_app(self):
        app = self._create_app()
        self._create_token(app, scope="read")
        self._create_token(app, scope="write")

        response = self.client.get("/api/oauth/connected-apps/")

        assert response.status_code == status.HTTP_200_OK
        assert len(response.json()) == 1
        assert set(response.json()[0]["scopes"]) == {"read", "write"}

    def test_list_returns_multiple_apps(self):
        app1 = self._create_app("App One")
        app2 = self._create_app("App Two")
        self._create_token(app1)
        self._create_token(app2)

        response = self.client.get("/api/oauth/connected-apps/")

        assert response.status_code == status.HTTP_200_OK
        assert len(response.json()) == 2

    def test_list_shows_verified_and_first_party_flags(self):
        app = self._create_app(is_verified=True, is_first_party=True)
        self._create_token(app)

        response = self.client.get("/api/oauth/connected-apps/")

        data = response.json()[0]
        assert data["is_verified"] is True
        assert data["is_first_party"] is True

    def test_revoke_deletes_all_tokens_for_app(self):
        app = self._create_app()
        self._create_token(app)
        self._create_token(app, scope="admin")

        response = self.client.post(f"/api/oauth/connected-apps/{app.id}/revoke/")

        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert OAuthAccessToken.objects.filter(user=self.user, application=app).count() == 0

    def test_revoke_also_revokes_refresh_tokens(self):
        app = self._create_app()
        access_token = self._create_token(app)
        OAuthRefreshToken.objects.create(
            user=self.user,
            application=app,
            token="refresh-token-1",
            access_token=access_token,
        )

        self.client.post(f"/api/oauth/connected-apps/{app.id}/revoke/")

        assert OAuthRefreshToken.objects.filter(user=self.user, application=app, revoked__isnull=True).count() == 0

    def test_revoke_also_deletes_grants(self):
        app = self._create_app()
        self._create_token(app)
        OAuthGrant.objects.create(
            user=self.user,
            application=app,
            redirect_uri="https://example.com/callback",
            expires=timezone.now() + timedelta(hours=1),
            scope="read",
            code_challenge="test_challenge",
            code_challenge_method="S256",
        )

        self.client.post(f"/api/oauth/connected-apps/{app.id}/revoke/")

        assert OAuthGrant.objects.filter(user=self.user, application=app).count() == 0

    def test_revoke_does_not_affect_other_users_tokens(self):
        other_user = User.objects.create_and_join(self.organization, "other@example.com", "password")
        app = self._create_app()
        self._create_token(app)
        self._create_token(app, user=other_user)

        self.client.post(f"/api/oauth/connected-apps/{app.id}/revoke/")

        assert OAuthAccessToken.objects.filter(user=other_user, application=app).count() == 1

    def test_revoke_nonexistent_app_returns_404(self):
        response = self.client.post(f"/api/oauth/connected-apps/{uuid.uuid4()}/revoke/")

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_revoke_app_with_no_active_tokens_returns_404(self):
        app = self._create_app()
        self._create_token(app, expires_hours=-1)

        response = self.client.post(f"/api/oauth/connected-apps/{app.id}/revoke/")

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_unauthenticated_request_is_rejected(self):
        unauthenticated_client = APIClient()
        response = unauthenticated_client.get("/api/oauth/connected-apps/")

        assert response.status_code in [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN]

    def test_list_returns_empty_when_no_connected_apps(self):
        response = self.client.get("/api/oauth/connected-apps/")

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == []
