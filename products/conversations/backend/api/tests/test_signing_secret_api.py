import time
from datetime import timedelta

from posthog.test.base import APIBaseTest

from django.conf import settings as django_settings

from parameterized import parameterized
from rest_framework import status

from posthog.jwt import PosthogJwtAudience, encode_jwt
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.organization import OrganizationMembership

from products.conversations.backend.models import SigningSecret


class TestSigningSecretAPI(APIBaseTest):
    def _url(self, suffix: str = "") -> str:
        return f"/api/projects/{self.team.id}/conversations/signing_secret/{suffix}"

    def _make_admin(self) -> None:
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

    def test_get_returns_the_secret(self):
        SigningSecret.objects.for_team(self.team.id).create(team=self.team, secret="phs_existing_secret")
        response = self.client.get(self._url())
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["secret"] == "phs_existing_secret"

    def test_get_without_a_row_returns_null(self):
        response = self.client.get(self._url())
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"secret": None, "updated_at": None}

    def test_rotate_mints_an_independent_secret_and_leaves_the_legacy_token_alone(self):
        self._make_admin()
        self.team.secret_api_token = "phs_legacy_token"
        self.team.save()
        SigningSecret.objects.for_team(self.team.id).create(team=self.team, secret="phs_legacy_token")

        response = self.client.post(self._url("rotate/"))

        assert response.status_code == status.HTTP_200_OK
        row = SigningSecret.objects.for_team(self.team.id).get()
        assert response.json()["secret"] == row.secret
        assert row.secret != "phs_legacy_token"
        assert row.rotated_independently is True
        self.team.refresh_from_db()
        assert self.team.secret_api_token == "phs_legacy_token"

        log = ActivityLog.objects.get(
            scope="Team", team_id=self.team.id, detail__changes__0__field="conversations_signing_secret"
        )
        assert log.user == self.user
        assert log.activity == "updated"
        assert log.detail is not None
        assert row.secret not in str(log.detail)
        change = log.detail["changes"][0]
        assert change["action"] == "changed"
        assert change["before"] is not None

    def test_rotate_requires_admin(self):
        response = self.client.post(self._url("rotate/"))
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert not SigningSecret.objects.for_team(self.team.id).exists()

    def test_rotate_requires_fresh_session(self):
        self._make_admin()
        session = self.client.session
        # login() stamps both keys and the freshness window takes their max, so age both.
        stale = time.time() - django_settings.SESSION_SENSITIVE_ACTIONS_AGE - 1
        session[django_settings.SESSION_COOKIE_CREATED_AT_KEY] = stale
        session[django_settings.SESSION_LAST_REAUTH_AT_KEY] = stale
        session.save()

        response = self.client.post(self._url("rotate/"))

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.json()["code"] == "sensitive_action_required_reauth"

    @parameterized.expand([("get",), ("post",)])
    def test_scoped_tokens_cannot_reach_the_raw_secret(self, method):
        # INTERNAL viewset: no scoped token may read or rotate the raw secret.
        self._make_admin()
        key_value = self.create_personal_api_key_with_scopes(["*"])
        self.client.logout()

        url = self._url() if method == "get" else self._url("rotate/")
        response = getattr(self.client, method)(url, HTTP_AUTHORIZATION=f"Bearer {key_value}")

        assert response.status_code == status.HTTP_403_FORBIDDEN

    @parameterized.expand([("get",), ("post",)])
    def test_impersonation_jwt_cannot_reach_the_raw_secret(self, method):
        # JWTs carry no session, so they would skip the freshness check if auth let them in.
        self._make_admin()
        token = encode_jwt({"id": self.user.id}, timedelta(minutes=15), PosthogJwtAudience.IMPERSONATED_USER)
        self.client.logout()

        url = self._url() if method == "get" else self._url("rotate/")
        response = getattr(self.client, method)(url, HTTP_AUTHORIZATION=f"Bearer {token}")

        assert response.status_code == status.HTTP_403_FORBIDDEN
