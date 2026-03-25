"""Tests that toolbar API endpoints accept OAuth Bearer token authentication.

OAuthAccessTokenAuthentication is wired into every TeamAndOrgViewSetMixin
endpoint via get_authenticators(). These tests verify that:
  1. Toolbar OAuth tokens (with TOOLBAR_OAUTH_SCOPES) grant access to every toolbar endpoint.
  2. Tokens with the exact required scope grant access; wrong scopes are rejected.
  3. Expired / invalid tokens are rejected.
  4. Unauthenticated requests are rejected.
"""

from datetime import timedelta

from posthog.test.base import APIBaseTest

from django.conf import settings
from django.test import override_settings
from django.utils import timezone

from parameterized import parameterized

from posthog.api.oauth.test_dcr import generate_rsa_key
from posthog.constants import AvailableFeature
from posthog.models.oauth import OAuthAccessToken, OAuthApplication
from posthog.models.organization import OrganizationMembership
from posthog.models.personal_api_key import PersonalAPIKey, hash_key_value
from posthog.models.utils import generate_random_token_personal


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


@override_settings(OAUTH2_PROVIDER={**settings.OAUTH2_PROVIDER, "OIDC_RSA_PRIVATE_KEY": generate_rsa_key()})
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
        (
            "feature_flags_evaluation_reasons",
            "/api/projects/{team_id}/feature_flags/evaluation_reasons/?distinct_id=test",
            "get",
            "feature_flag",
        ),
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


@override_settings(OAUTH2_PROVIDER={**settings.OAUTH2_PROVIDER, "OIDC_RSA_PRIVATE_KEY": generate_rsa_key()})
class TestToolbarOAuthBypassesPersonalApiKeyRestriction(APIBaseTest):
    """
    When an organization disables personal API keys for members,
    toolbar OAuth tokens should still work for non-admin users.
    """

    def setUp(self):
        super().setUp()

        self.organization.available_product_features = [{"key": AvailableFeature.ORGANIZATION_SECURITY_SETTINGS}]
        self.organization.members_can_use_personal_api_keys = False
        self.organization.save()

        self.oauth_app = _make_oauth_app(self.organization, self.user)
        toolbar_scopes = " ".join(settings.TOOLBAR_OAUTH_SCOPES)
        self.toolbar_token = _make_token(self.user, self.oauth_app, "pha_bypass_test", scope=toolbar_scopes)

    @parameterized.expand(TestToolbarEndpointOAuthAuth.TOOLBAR_ENDPOINTS)
    def test_member_with_oauth_token_not_blocked_by_personal_api_key_restriction(
        self, _label, url_template, method, _scope
    ):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        self.client.logout()
        url = url_template.format(team_id=self.team.id)
        response = getattr(self.client, method)(
            url,
            HTTP_AUTHORIZATION=f"Bearer {self.toolbar_token.token}",
        )
        assert response.status_code not in (401, 403), (
            f"OAuth token should bypass personal API key restriction, got {response.status_code}: {response.content[:300]}"
        )

    def test_member_with_personal_api_key_still_blocked(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        personal_api_key = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="X",
            user=self.user,
            secure_value=hash_key_value(personal_api_key),
            scopes=["*"],
        )

        self.client.logout()
        response = self.client.get(
            f"/api/projects/{self.team.id}/feature_flags/",
            HTTP_AUTHORIZATION=f"Bearer {personal_api_key}",
        )
        assert response.status_code == 403, f"Personal API key should still be blocked, got {response.status_code}"


@override_settings(OAUTH2_PROVIDER={**settings.OAUTH2_PROVIDER, "OIDC_RSA_PRIVATE_KEY": generate_rsa_key()})
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


@override_settings(OAUTH2_PROVIDER={**settings.OAUTH2_PROVIDER, "OIDC_RSA_PRIVATE_KEY": generate_rsa_key()})
class TestHedgehogConfigOAuthAuth(APIBaseTest):
    """hedgehog_config uses /api/users/@me/ path, not team-scoped, so tested separately."""

    def setUp(self):
        super().setUp()
        self.oauth_app = _make_oauth_app(self.organization, self.user)

    def _url(self):
        return f"/api/users/@me/hedgehog_config/"

    def test_read_token_grants_get_access(self):
        token = _make_token(self.user, self.oauth_app, "pha_hh_read", scope="user:read")
        self.client.logout()
        response = self.client.get(self._url(), HTTP_AUTHORIZATION=f"Bearer {token.token}")
        assert response.status_code == 200

    def test_read_token_rejected_for_patch(self):
        token = _make_token(self.user, self.oauth_app, "pha_hh_read_patch", scope="user:read")
        self.client.logout()
        response = self.client.patch(
            self._url(),
            data={"color": "red"},
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token.token}",
        )
        assert response.status_code == 403

    def test_write_token_grants_patch_access(self):
        token = _make_token(self.user, self.oauth_app, "pha_hh_write", scope="user:write")
        self.client.logout()
        response = self.client.patch(
            self._url(),
            data={"color": "red"},
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token.token}",
        )
        assert response.status_code == 200

    def test_expired_token_is_rejected(self):
        token = _make_token(self.user, self.oauth_app, "pha_hh_exp", scope="user:read", delta_hours=-1)
        self.client.logout()
        response = self.client.get(self._url(), HTTP_AUTHORIZATION=f"Bearer {token.token}")
        assert response.status_code == 401

    def test_unauthenticated_is_rejected(self):
        self.client.logout()
        response = self.client.get(self._url())
        assert response.status_code in (401, 403)


@override_settings(OAUTH2_PROVIDER={**settings.OAUTH2_PROVIDER, "OIDC_RSA_PRIVATE_KEY": generate_rsa_key()})
class TestToolbarOAuthScopesConfig(APIBaseTest):
    """Verify TOOLBAR_OAUTH_SCOPES covers every toolbar endpoint scope."""

    EXPECTED_SCOPES = [
        "action:read",
        "action:write",
        "feature_flag:read",
        "experiment:read",
        "experiment:write",
        "product_tour:read",
        "product_tour:write",
        "query:read",
        "heatmap:read",
        "element:read",
        "uploaded_media:write",
        "user:read",
    ]

    @parameterized.expand([(s,) for s in EXPECTED_SCOPES])
    def test_scope_is_configured(self, scope):
        assert scope in settings.TOOLBAR_OAUTH_SCOPES, f"Missing toolbar scope: {scope}"

    def test_no_wildcard_scope(self):
        assert "*" not in settings.TOOLBAR_OAUTH_SCOPES, "Toolbar should use specific scopes, not wildcard"


class TestOAuthCorsPreflightMiddleware(APIBaseTest):
    """The toolbar runs in the customer's page and uses window.fetch.
    Customer code may monkey-patch fetch to inject custom headers
    (e.g. x-app-version). The CORS preflight must echo back whatever
    headers the browser requests so the actual request isn't blocked."""

    OAUTH_CORS_PATHS = [
        ("oauth_token_slash", "/oauth/token/"),
        ("oauth_token_no_slash", "/oauth/token"),
        ("toolbar_oauth_check_no_slash", "/toolbar_oauth/check"),
        ("toolbar_oauth_check_slash", "/toolbar_oauth/check/"),
    ]

    @parameterized.expand(OAUTH_CORS_PATHS)
    def test_preflight_echoes_back_custom_headers(self, _label, path):
        response = self.client.options(
            path,
            HTTP_ORIGIN="https://www.example.com",
            HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST",
            HTTP_ACCESS_CONTROL_REQUEST_HEADERS="content-type,x-app-version,x-custom-header",
        )
        assert response.status_code == 200
        assert response["Access-Control-Allow-Origin"] == "https://www.example.com"
        assert "x-app-version" in response["Access-Control-Allow-Headers"]
        assert "x-custom-header" in response["Access-Control-Allow-Headers"]
        assert response["Access-Control-Max-Age"] == "86400"
        # Uses Bearer tokens, not cookies — no credentials header
        assert not response.has_header("Access-Control-Allow-Credentials")

    @parameterized.expand(OAUTH_CORS_PATHS)
    def test_non_preflight_get_passes_through(self, _label, path):
        response = self.client.get(path)
        assert not response.has_header("Access-Control-Allow-Headers")

    @parameterized.expand(OAUTH_CORS_PATHS)
    def test_non_preflight_post_passes_through(self, _label, path):
        response = self.client.post(
            path,
            HTTP_ORIGIN="https://www.example.com",
        )
        # POST should not be intercepted — it flows through to django-cors-headers
        assert not response.has_header("Access-Control-Max-Age")

    @parameterized.expand(OAUTH_CORS_PATHS)
    def test_preflight_without_origin_passes_through(self, _label, path):
        response = self.client.options(
            path,
            HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST",
            HTTP_ACCESS_CONTROL_REQUEST_HEADERS="content-type",
        )
        # OPTIONS without Origin is not a CORS preflight — should not be intercepted
        assert not response.has_header("Access-Control-Max-Age")

    def test_preflight_to_unrelated_path_not_intercepted(self):
        response = self.client.options(
            f"/api/projects/{self.team.id}/actions/",
            HTTP_ORIGIN="https://www.example.com",
            HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST",
            HTTP_ACCESS_CONTROL_REQUEST_HEADERS="content-type,x-app-version",
        )
        # Should be handled by django-cors-headers, not our middleware
        allow_headers = response.get("Access-Control-Allow-Headers", "")
        assert "x-app-version" not in allow_headers
