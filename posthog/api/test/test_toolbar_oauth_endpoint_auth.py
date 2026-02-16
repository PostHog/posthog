"""Tests that toolbar API endpoints accept OAuth Bearer token authentication.

OAuthAccessTokenAuthentication is wired into every TeamAndOrgViewSetMixin
endpoint via get_authenticators(). These tests verify that:
  1. Toolbar OAuth tokens (with TOOLBAR_OAUTH_SCOPES) grant access to every toolbar endpoint.
  2. Tokens with the exact required scope grant access; wrong scopes are rejected.
  3. Expired / invalid tokens are rejected.
  4. Temporary token auth still works (backward compat).
"""

from datetime import timedelta

from posthog.test.base import APIBaseTest

from django.conf import settings
from django.utils import timezone

from parameterized import parameterized

from posthog.models.oauth import OAuthAccessToken, OAuthApplication


def _make_oauth_app(organization, user):
    return OAuthApplication.objects.create(
        name="Toolbar Test App",
        client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
        authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
        redirect_uris="https://example.com/callback",
        algorithm="RS256",
        skip_authorization=False,
        organization=organization,
        user=user,
    )


def _make_token(user, app, token_str, scope="*", delta_hours=1):
    return OAuthAccessToken.objects.create(
        user=user,
        application=app,
        token=token_str,
        expires=timezone.now() + timedelta(hours=delta_hours),
        scope=scope,
    )


class TestToolbarEndpointOAuthAuth(APIBaseTest):
    """
    Every toolbar-consumed endpoint should accept OAuth access tokens
    with the scopes defined in settings.TOOLBAR_OAUTH_SCOPES.
    """

    def setUp(self):
        super().setUp()
        self.oauth_app = _make_oauth_app(self.organization, self.user)

        toolbar_scopes = " ".join(settings.TOOLBAR_OAUTH_SCOPES)
        self.toolbar_token = _make_token(self.user, self.oauth_app, "pha_toolbar_full", scope=toolbar_scopes)
        self.expired_token = _make_token(
            self.user, self.oauth_app, "pha_toolbar_expired", scope=toolbar_scopes, delta_hours=-1
        )

    # (label, url_template, http_method, scope_object)
    TOOLBAR_ENDPOINTS = [
        ("actions_list", "/api/projects/{team_id}/actions/", "get", "action"),
        ("feature_flags_list", "/api/projects/{team_id}/feature_flags/", "get", "feature_flag"),
        ("feature_flags_my_flags", "/api/projects/{team_id}/feature_flags/my_flags/", "get", "feature_flag"),
        ("web_experiments_list", "/api/projects/{team_id}/web_experiments/", "get", "experiment"),
        ("product_tours_list", "/api/projects/{team_id}/product_tours/", "get", "product_tour"),
        ("web_vitals_list", "/api/environments/{team_id}/web_vitals/?pathname=/", "get", "query"),
        ("heatmaps_list", "/api/environments/{team_id}/heatmaps/", "get", "heatmap"),
        ("elements_stats", "/api/environments/{team_id}/elements/stats/", "get", "element"),
    ]

    def _url(self, template: str) -> str:
        return template.format(team_id=self.team.id)

    def _request(self, method: str, url: str, **kwargs):
        return getattr(self.client, method)(url, **kwargs)

    # -- Full toolbar token grants access -----------------------------------

    @parameterized.expand(TOOLBAR_ENDPOINTS)
    def test_toolbar_oauth_token_authenticates(self, _label, url_template, method, _scope):
        self.client.logout()
        response = self._request(
            method,
            self._url(url_template),
            HTTP_AUTHORIZATION=f"Bearer {self.toolbar_token.token}",
        )
        assert response.status_code not in (401, 403), (
            f"Expected access, got {response.status_code}: {response.content[:300]}"
        )

    # -- Correct scope grants access ----------------------------------------

    @parameterized.expand(TOOLBAR_ENDPOINTS)
    def test_correct_scope_grants_access(self, _label, url_template, method, scope_object):
        token = _make_token(
            self.user,
            self.oauth_app,
            f"pha_scoped_{scope_object}",
            scope=f"{scope_object}:read",
        )
        self.client.logout()
        response = self._request(
            method,
            self._url(url_template),
            HTTP_AUTHORIZATION=f"Bearer {token.token}",
        )
        assert response.status_code not in (401, 403), (
            f"Scope '{scope_object}:read' should grant access, got {response.status_code}: {response.content[:300]}"
        )

    # -- Wrong scope is rejected --------------------------------------------

    @parameterized.expand(TOOLBAR_ENDPOINTS)
    def test_wrong_scope_is_rejected(self, _label, url_template, method, _scope):
        token = _make_token(
            self.user,
            self.oauth_app,
            f"pha_wrong_{_scope}",
            scope="some_unrelated_scope:read",
        )
        self.client.logout()
        response = self._request(
            method,
            self._url(url_template),
            HTTP_AUTHORIZATION=f"Bearer {token.token}",
        )
        assert response.status_code == 403, f"Wrong scope should be rejected with 403, got {response.status_code}"

    # -- Expired token is rejected ------------------------------------------

    @parameterized.expand(TOOLBAR_ENDPOINTS)
    def test_expired_token_is_rejected(self, _label, url_template, method, _scope):
        self.client.logout()
        response = self._request(
            method,
            self._url(url_template),
            HTTP_AUTHORIZATION=f"Bearer {self.expired_token.token}",
        )
        assert response.status_code == 401

    # -- Invalid token is rejected ------------------------------------------

    @parameterized.expand(TOOLBAR_ENDPOINTS)
    def test_nonexistent_token_is_rejected(self, _label, url_template, method, _scope):
        self.client.logout()
        response = self._request(
            method,
            self._url(url_template),
            HTTP_AUTHORIZATION="Bearer pha_does_not_exist",
        )
        assert response.status_code == 401

    # -- No auth at all is rejected -----------------------------------------

    @parameterized.expand(TOOLBAR_ENDPOINTS)
    def test_unauthenticated_is_rejected(self, _label, url_template, method, _scope):
        self.client.logout()
        response = self._request(method, self._url(url_template))
        assert response.status_code in (401, 403)

    # -- Non-pha Bearer token falls through ---------------------------------

    @parameterized.expand(TOOLBAR_ENDPOINTS)
    def test_non_pha_bearer_is_ignored(self, _label, url_template, method, _scope):
        self.client.logout()
        response = self._request(
            method,
            self._url(url_template),
            HTTP_AUTHORIZATION="Bearer not_a_pha_token",
        )
        assert response.status_code in (401, 403)

    # -- Temporary token backward compat ------------------------------------

    @parameterized.expand(TOOLBAR_ENDPOINTS)
    def test_temporary_token_still_works(self, _label, url_template, method, _scope):
        self.client.logout()
        self.user.temporary_token = "tmp_test_tok"
        self.user.save(update_fields=["temporary_token"])

        url = self._url(url_template)
        sep = "&" if "?" in url else "?"
        response = self._request(method, f"{url}{sep}temporary_token=tmp_test_tok")
        assert response.status_code not in (401, 403), (
            f"Temporary token should still work, got {response.status_code}: {response.content[:300]}"
        )


class TestUploadedMediaOAuthAuth(APIBaseTest):
    """uploaded_media is tested separately — its only toolbar action is POST (upload)."""

    def setUp(self):
        super().setUp()
        self.oauth_app = _make_oauth_app(self.organization, self.user)
        self.write_token = _make_token(self.user, self.oauth_app, "pha_media_write", scope="uploaded_media:write")
        self.read_token = _make_token(self.user, self.oauth_app, "pha_media_read", scope="uploaded_media:read")
        self.expired_token = _make_token(
            self.user, self.oauth_app, "pha_media_exp", scope="uploaded_media:write", delta_hours=-1
        )

    def _url(self):
        return f"/api/projects/{self.team.id}/uploaded_media/"

    def test_write_token_authenticates_for_upload(self):
        self.client.logout()
        response = self.client.post(
            self._url(),
            HTTP_AUTHORIZATION=f"Bearer {self.write_token.token}",
        )
        # Auth passes; request fails on missing file, not auth
        assert response.status_code != 401

    def test_read_token_rejected_for_upload(self):
        self.client.logout()
        response = self.client.post(
            self._url(),
            HTTP_AUTHORIZATION=f"Bearer {self.read_token.token}",
        )
        assert response.status_code == 403

    def test_expired_token_is_rejected(self):
        self.client.logout()
        response = self.client.post(
            self._url(),
            HTTP_AUTHORIZATION=f"Bearer {self.expired_token.token}",
        )
        assert response.status_code == 401

    def test_unauthenticated_is_rejected(self):
        self.client.logout()
        response = self.client.post(self._url())
        assert response.status_code in (401, 403)

    def test_temporary_token_still_works(self):
        self.client.logout()
        self.user.temporary_token = "tmp_media_tok"
        self.user.save(update_fields=["temporary_token"])
        response = self.client.post(f"{self._url()}?temporary_token=tmp_media_tok")
        assert response.status_code != 401


class TestToolbarOAuthScopesConfig(APIBaseTest):
    """Verify TOOLBAR_OAUTH_SCOPES covers every toolbar endpoint scope."""

    EXPECTED_SCOPES = [
        "action:read",
        "action:write",
        "feature_flag:read",
        "feature_flag:write",
        "experiment:read",
        "experiment:write",
        "product_tour:read",
        "product_tour:write",
        "query:read",
        "heatmap:read",
        "heatmap:write",
        "element:read",
        "uploaded_media:read",
        "uploaded_media:write",
        "user:read",
        "user:write",
    ]

    @parameterized.expand([(s,) for s in EXPECTED_SCOPES])
    def test_scope_is_configured(self, scope):
        assert scope in settings.TOOLBAR_OAUTH_SCOPES, f"Missing toolbar scope: {scope}"

    def test_no_wildcard_scope(self):
        assert "*" not in settings.TOOLBAR_OAUTH_SCOPES, "Toolbar should use specific scopes, not wildcard"
