"""Tests for the Team.toolbar_disabled kill switch.

These cover every backend toolbar access point and confirm that when
team.toolbar_disabled is True, the endpoint refuses with a 403 (or the
endpoint's local error shape) before any token, redirect, or flag data
is issued. Default state (toolbar_disabled=False) is also exercised to
ensure baseline behavior is unchanged.
"""

import json

import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.conf import settings
from django.test import override_settings

from parameterized import parameterized

from posthog.api.oauth.test_dcr import generate_rsa_key
from posthog.api.oauth.toolbar_service import ToolbarOAuthError, assert_toolbar_enabled
from posthog.models.oauth import OAuthApplication, OAuthRefreshToken


@override_settings(OAUTH2_PROVIDER={**settings.OAUTH2_PROVIDER, "OIDC_RSA_PRIVATE_KEY": generate_rsa_key()})
class TestToolbarDisabledAuthorize(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.team.app_urls = ["https://mysite.com"]
        self.team.save()
        self.user.current_team = self.team
        self.user.save(update_fields=["current_team"])
        self.client.force_login(self.user)

    def _authorize(self):
        return self.client.get("/toolbar_oauth/authorize/?redirect=https://mysite.com/page&code_challenge=abc")

    def test_default_allows_authorize(self):
        response = self._authorize()
        assert response.status_code == 302

    def test_disabled_blocks_authorize(self):
        self.team.toolbar_disabled = True
        self.team.save()
        response = self._authorize()
        assert response.status_code == 403
        content = response.content.decode()
        assert "Toolbar disabled" in content
        assert "environment-toolbar" in content


@override_settings(OAUTH2_PROVIDER={**settings.OAUTH2_PROVIDER, "OIDC_RSA_PRIVATE_KEY": generate_rsa_key()})
class TestToolbarDisabledCallback(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.team.app_urls = ["https://mysite.com"]
        self.team.save()
        self.client.force_login(self.user)

    def test_disabled_blocks_callback_before_state_validation(self):
        self.team.toolbar_disabled = True
        self.team.save()
        response = self.client.get("/toolbar_oauth/callback?code=abc&state=garbage")
        # The toolbar_disabled check fires before state validation,
        # so we get a plain 403 with the disabled detail, not a state error.
        assert response.status_code == 403
        assert b"Toolbar is disabled" in response.content


class TestToolbarDisabledPreloadedFlags(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)

    def test_disabled_blocks_prepare_preloaded_flags(self):
        self.team.toolbar_disabled = True
        self.team.save()
        response = self.client.post(
            "/api/user/prepare_toolbar_preloaded_flags",
            data=json.dumps({"distinct_id": "test"}),
            content_type="application/json",
        )
        assert response.status_code == 403
        body = response.json()
        assert body["code"] == "toolbar_disabled"

    def test_disabled_blocks_get_preloaded_flags(self):
        self.team.toolbar_disabled = True
        self.team.save()
        response = self.client.get("/api/user/get_toolbar_preloaded_flags?key=anything")
        assert response.status_code == 403
        body = response.json()
        assert body["code"] == "toolbar_disabled"


class TestToolbarDisabledRedirectToSite(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.team.app_urls = ["https://mysite.com"]
        self.team.save()
        self.client.force_login(self.user)

    def test_default_allows_redirect(self):
        response = self.client.get("/api/user/redirect_to_site/?appUrl=https://mysite.com/page")
        assert response.status_code == 302

    def test_disabled_blocks_redirect(self):
        self.team.toolbar_disabled = True
        self.team.save()
        response = self.client.get("/api/user/redirect_to_site/?appUrl=https://mysite.com/page")
        assert response.status_code == 403
        content = response.content.decode()
        assert "Toolbar disabled" in content


@override_settings(OAUTH2_PROVIDER={**settings.OAUTH2_PROVIDER, "OIDC_RSA_PRIVATE_KEY": generate_rsa_key()})
class TestToolbarDisabledRefresh(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.user.current_team = self.team
        self.user.save(update_fields=["current_team"])

        self.oauth_app = OAuthApplication.objects.create(
            name="Toolbar Test App",
            client_type=OAuthApplication.CLIENT_PUBLIC,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://example.com/callback",
            algorithm="RS256",
            organization=self.organization,
            user=self.user,
            is_first_party=True,
        )
        self.refresh_token_str = "test_refresh_token_value"
        OAuthRefreshToken.objects.create(
            user=self.user,
            application=self.oauth_app,
            token=self.refresh_token_str,
        )

    def _refresh(self):
        return self.client.post(
            "/api/user/toolbar_oauth_refresh",
            data=json.dumps({"refresh_token": self.refresh_token_str, "client_id": self.oauth_app.client_id}),
            content_type="application/json",
        )

    def test_disabled_blocks_refresh_before_calling_oauth_server(self):
        self.team.toolbar_disabled = True
        self.team.save()
        with patch("posthog.api.user.refresh_tokens") as mock_refresh:
            response = self._refresh()
        assert response.status_code == 403
        body = response.json()
        assert body["code"] == "toolbar_disabled"
        # The refresh call must never reach the OAuth server once disabled
        mock_refresh.assert_not_called()


class TestAssertToolbarEnabled(APIBaseTest):
    """Unit tests for the assert_toolbar_enabled helper."""

    @parameterized.expand([("false", False), ("null", None)])
    def test_passes_when_not_disabled(self, _label, value):
        self.team.toolbar_disabled = value
        self.team.save()
        assert_toolbar_enabled(self.team)  # no exception

    def test_raises_when_disabled(self):
        self.team.toolbar_disabled = True
        self.team.save()
        with pytest.raises(ToolbarOAuthError) as exc_info:
            assert_toolbar_enabled(self.team)
        assert exc_info.value.code == "toolbar_disabled"
        assert exc_info.value.status_code == 403

    def test_raises_on_none_team(self):
        with pytest.raises(ToolbarOAuthError) as exc_info:
            assert_toolbar_enabled(None)
        assert exc_info.value.code == "toolbar_disabled"
