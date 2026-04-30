import time

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import override_settings

from rest_framework import status

from posthog.models import User
from posthog.models.integration import GitHubInstallationAccess, GitHubUserAuthorization, Integration
from posthog.models.user_integration import (
    ReauthorizationRequired,
    UserGitHubIntegration,
    UserIntegration,
    user_github_integration_from_installation,
)


def _authorization(gh_id: int = 99, gh_login: str = "octocat") -> GitHubUserAuthorization:
    return GitHubUserAuthorization(
        gh_id=gh_id,
        gh_login=gh_login,
        access_token="gho_access",
        refresh_token="ghr_refresh",
        access_token_expires_in=28800,
        refresh_token_expires_in=15897600,
    )


def _create_user_integration(user: User, **overrides) -> UserIntegration:
    now = int(time.time())
    defaults = {
        "kind": "github",
        "integration_id": "12345",
        "config": {
            "installation_id": "12345",
            "expires_in": 3600,
            "refreshed_at": now,
            "repository_selection": "selected",
            "account": {"type": "User", "name": "octocat"},
            "github_user": {"login": "octocat", "id": 99},
            "user_token_refreshed_at": now,
            "user_access_token_expires_at": now + 28800,
            "user_refresh_token_expires_at": now + 15897600,
        },
        "sensitive_config": {
            "access_token": "ghs_install_token",
            "user_access_token": "gho_access",
            "user_refresh_token": "ghr_refresh",
        },
    }
    defaults.update(overrides)
    return UserIntegration.objects.create(user=user, **defaults)


class TestUserIntegrationEndpoints(APIBaseTest):
    def test_list_returns_empty_when_no_integrations(self):
        response = self.client.get("/api/users/@me/integrations/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.json()["results"]
        self.assertEqual(len(results), 0)

    def test_list_returns_github_integration(self):
        _create_user_integration(self.user)
        response = self.client.get("/api/users/@me/integrations/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.json()["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["installation_id"], "12345")
        self.assertFalse(results[0]["uses_shared_installation"])

    def test_list_returns_multiple_github_integrations(self):
        _create_user_integration(self.user, integration_id="12345")
        _create_user_integration(
            self.user,
            integration_id="67890",
            config={
                "installation_id": "67890",
                "expires_in": 3600,
                "refreshed_at": int(time.time()),
                "repository_selection": "all",
                "account": {"type": "Organization", "name": "PostHog"},
                "github_user": {"login": "octocat", "id": 99},
                "user_token_refreshed_at": int(time.time()),
            },
        )
        response = self.client.get("/api/users/@me/integrations/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.json()["results"]
        self.assertEqual(len(results), 2)
        installation_ids = {r["installation_id"] for r in results}
        self.assertEqual(installation_ids, {"12345", "67890"})

    def test_list_detects_shared_installation(self):
        _create_user_integration(self.user)
        Integration.objects.create(
            team=self.team,
            kind="github",
            integration_id="12345",
            config={"account": {"name": "PostHog"}},
            sensitive_config={},
        )
        response = self.client.get("/api/users/@me/integrations/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.json()["results"]
        self.assertTrue(results[0]["uses_shared_installation"])

    def test_list_team_github_only_yields_empty_results(self):
        Integration.objects.create(
            team=self.team,
            kind="github",
            integration_id="99999",
            config={"account": {"name": "PostHog"}},
            sensitive_config={},
        )
        response = self.client.get("/api/users/@me/integrations/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["results"]), 0)

    def test_delete_removes_specific_installation(self):
        _create_user_integration(self.user, integration_id="12345")
        _create_user_integration(self.user, integration_id="67890")
        response = self.client.delete("/api/users/@me/integrations/github/12345/")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(UserIntegration.objects.filter(user=self.user, kind="github", integration_id="12345").exists())
        self.assertTrue(UserIntegration.objects.filter(user=self.user, kind="github", integration_id="67890").exists())

    def test_delete_returns_404_when_installation_not_found(self):
        response = self.client.delete("/api/users/@me/integrations/github/99999/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    @override_settings(GITHUB_APP_CLIENT_ID="client_id")
    @patch(
        "posthog.api.user_integration.get_instance_settings",
        return_value={"GITHUB_APP_SLUG": "posthog-dev"},
    )
    def test_github_start_returns_install_url_when_no_team_github(self, _mock_settings):
        response = self.client.post("/api/users/@me/integrations/github/start/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertIn("install_url", data)
        self.assertEqual(data.get("connect_flow"), "app_install")
        self.assertIn("github.com/apps/posthog-dev/installations/new", data["install_url"])

    @override_settings(GITHUB_APP_CLIENT_ID="gh_client_123")
    @patch(
        "posthog.api.user_integration.get_instance_settings",
        return_value={"GITHUB_APP_SLUG": "posthog-dev"},
    )
    def test_github_start_returns_install_url_even_when_team_has_github_integration(self, _mock_settings):
        Integration.objects.create(
            team=self.team,
            kind="github",
            integration_id="12345678",
            config={"account": {"name": "acme"}},
            sensitive_config={},
            created_by=self.user,
        )
        response = self.client.post("/api/users/@me/integrations/github/start/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertIn("install_url", data)
        self.assertEqual(data.get("connect_flow"), "app_install")
        self.assertIn("github.com/apps/posthog-dev/installations/new", data["install_url"])

    @override_settings(
        GITHUB_APP_CLIENT_ID="gh_client_123", SITE_URL="https://us.posthog.com", GITHUB_APP_CLIENT_SECRET="s"
    )
    def test_github_start_posthog_code_fast_path_returns_oauth_url(self):
        Integration.objects.create(
            team=self.team,
            kind="github",
            integration_id="12345678",
            config={"account": {"name": "acme"}},
            sensitive_config={},
            created_by=self.user,
        )
        response = self.client.post(
            "/api/users/@me/integrations/github/start/",
            {"connect_from": "posthog_code"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertIn("install_url", data)
        self.assertEqual(data.get("connect_flow"), "oauth_authorize")
        url = data["install_url"]
        self.assertIn("github.com/login/oauth/authorize", url)
        self.assertIn("client_id=gh_client_123", url)
        self.assertIn("redirect_uri=https%3A%2F%2Fus.posthog.com%2Fcomplete%2Fgithub-link%2F", url)

    @override_settings(GITHUB_APP_CLIENT_ID="gh_client_123")
    @patch(
        "posthog.api.user_integration.get_instance_settings",
        return_value={"GITHUB_APP_SLUG": "posthog-dev"},
    )
    def test_github_start_posthog_code_skips_fast_path_when_already_linked(self, _mock_settings):
        integration = Integration.objects.create(
            team=self.team,
            kind="github",
            integration_id="12345678",
            config={"account": {"name": "acme"}},
            sensitive_config={},
            created_by=self.user,
        )
        UserIntegration.objects.create(
            user=self.user,
            kind="github",
            integration_id=integration.integration_id,
            config={},
            sensitive_config={},
        )
        response = self.client.post(
            "/api/users/@me/integrations/github/start/",
            {"connect_from": "posthog_code"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data.get("connect_flow"), "app_install")
        self.assertIn("github.com/apps/posthog-dev/installations/new", data["install_url"])

    @override_settings(GITHUB_APP_CLIENT_ID="gh_client_123")
    @patch("posthog.api.user_integration._has_unlinked_github_installations", return_value=False)
    @patch(
        "posthog.api.user_integration.get_instance_settings",
        return_value={"GITHUB_APP_SLUG": "posthog-dev"},
    )
    def test_github_start_rejects_when_all_installations_linked(self, _mock_settings, _mock_unlinked):
        UserIntegration.objects.create(
            user=self.user,
            kind="github",
            integration_id="12345678",
            config={},
            sensitive_config={"user_access_token": "ghu_test"},
        )
        response = self.client.post("/api/users/@me/integrations/github/start/")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("already linked", response.json()["detail"])

    def test_github_start_without_app_slug_returns_400(self):
        with patch(
            "posthog.api.user_integration.get_instance_settings",
            return_value={"GITHUB_APP_SLUG": ""},
        ):
            response = self.client.post("/api/users/@me/integrations/github/start/")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @override_settings(
        GITHUB_APP_CLIENT_ID="client_id",
        GITHUB_APP_CLIENT_SECRET="client_secret",
        SITE_URL="https://us.posthog.com",
    )
    @patch("posthog.api.user_integration.requests.get")
    @patch("posthog.models.integration.GitHubIntegration.client_request")
    @patch("posthog.models.integration.GitHubIntegration.github_user_from_code")
    def test_github_link_oauth_callback_creates_user_integration_without_installation_in_query(
        self, mock_user_from_code, mock_client_request, mock_verify_get
    ):
        """OAuth-only flow: GET has code + state; installation_id is only in server state cache."""
        mock_verify_get.return_value = MagicMock(status_code=200)
        mock_user_from_code.return_value = _authorization()
        mock_install_info = MagicMock()
        mock_install_info.json.return_value = {
            "account": {"type": "User", "login": "octocat"},
        }
        mock_access_token = MagicMock()
        mock_access_token.json.return_value = {
            "token": "ghs_install_token",
            "expires_at": "2099-01-01T00:00:00Z",
            "repository_selection": "selected",
        }
        mock_client_request.side_effect = [mock_install_info, mock_access_token]

        Integration.objects.create(
            team=self.team,
            kind="github",
            integration_id="12345",
            config={},
            sensitive_config={},
            created_by=self.user,
        )
        state = "tok_oauth_123"
        cache.set(
            f"github_user_install_state:{state}",
            {
                "user_id": self.user.id,
                "installation_id": "12345",
                "flow": "oauth_authorize",
            },
            timeout=600,
        )
        from urllib.parse import urlencode

        state_q = urlencode({"token": state, "source": "user_integration"})

        response = self.client.get(
            "/complete/github-link/",
            {"code": "test_code", "state": state_q},
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn("github_link_success=1", response["Location"])
        mock_user_from_code.assert_called_once_with(
            "test_code", redirect_uri="https://us.posthog.com/complete/github-link/"
        )

        integration = UserIntegration.objects.get(user=self.user, kind="github")
        self.assertEqual(integration.integration_id, "12345")

    @override_settings(GITHUB_APP_CLIENT_ID="client_id", GITHUB_APP_CLIENT_SECRET="client_secret")
    @patch("posthog.api.user_integration.requests.get")
    @patch("posthog.models.integration.GitHubIntegration.client_request")
    @patch("posthog.models.integration.GitHubIntegration.github_user_from_code")
    def test_github_link_callback_creates_user_integration(
        self, mock_user_from_code, mock_client_request, mock_verify_get
    ):
        mock_verify_get.return_value = MagicMock(status_code=200)
        mock_user_from_code.return_value = _authorization()
        mock_install_info = MagicMock()
        mock_install_info.json.return_value = {
            "account": {"type": "User", "login": "octocat"},
        }
        mock_access_token = MagicMock()
        mock_access_token.json.return_value = {
            "token": "ghs_install_token",
            "expires_at": "2099-01-01T00:00:00Z",
            "repository_selection": "selected",
        }
        mock_client_request.side_effect = [mock_install_info, mock_access_token]

        state = "test_state_123"
        cache.set(f"github_user_install_state:{state}", {"user_id": self.user.id}, timeout=600)

        response = self.client.get(
            "/complete/github-link/",
            {"installation_id": "12345", "code": "test_code", "state": state},
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn("github_link_success=1", response["Location"])

        integration = UserIntegration.objects.get(user=self.user, kind="github")
        self.assertEqual(integration.integration_id, "12345")
        self.assertEqual(integration.config["github_user"]["login"], "octocat")
        self.assertEqual(integration.sensitive_config["user_access_token"], "gho_access")
        self.assertEqual(integration.sensitive_config["access_token"], "ghs_install_token")

    @override_settings(GITHUB_APP_CLIENT_ID="client_id", GITHUB_APP_CLIENT_SECRET="client_secret")
    @patch("posthog.api.user_integration.requests.get")
    @patch("posthog.models.integration.GitHubIntegration.client_request")
    @patch("posthog.models.integration.GitHubIntegration.github_user_from_code")
    def test_github_link_redirects_to_account_integration_connected_when_posthog_code(
        self, mock_user_from_code, mock_client_request, mock_verify_get
    ):
        """PostHog Code passes ``connect_from`` via start payload → cache; success uses return-to-app page."""
        mock_verify_get.return_value = MagicMock(status_code=200)
        mock_user_from_code.return_value = _authorization()
        mock_install_info = MagicMock()
        mock_install_info.json.return_value = {
            "account": {"type": "User", "login": "octocat"},
        }
        mock_access_token = MagicMock()
        mock_access_token.json.return_value = {
            "token": "ghs_install_token",
            "expires_at": "2099-01-01T00:00:00Z",
            "repository_selection": "selected",
        }
        mock_client_request.side_effect = [mock_install_info, mock_access_token]

        state = "test_state_posthog_code"
        cache.set(
            f"github_user_install_state:{state}",
            {"user_id": self.user.id, "connect_from": "posthog_code"},
            timeout=600,
        )

        response = self.client.get(
            "/complete/github-link/",
            {"installation_id": "12345", "code": "test_code", "state": state},
        )

        self.assertEqual(response.status_code, 302)
        loc = response["Location"]
        self.assertIn("/account-connected/github-integration", loc)
        self.assertIn("provider=github", loc)

    def test_github_link_callback_rejects_mismatched_state(self):
        cache.set("github_user_install_state:valid_state", {"user_id": self.user.id}, timeout=600)
        response = self.client.get(
            "/complete/github-link/",
            {"installation_id": "123", "code": "test_code", "state": "wrong_state"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("github_link_error=invalid_state", response["Location"])

    def test_github_link_callback_rejects_missing_params(self):
        response = self.client.get("/complete/github-link/", {"code": "test_code"})
        self.assertEqual(response.status_code, 302)
        self.assertIn("github_link_error=missing_params", response["Location"])


class TestGetGithubLoginPrecedence(APIBaseTest):
    """User.get_github_login() precedence: UserIntegration > UserSocialAuth > team Integration."""

    def test_returns_none_when_no_source_present(self):
        self.assertIsNone(self.user.get_github_login())

    def test_uses_user_integration_when_only_source(self):
        _create_user_integration(self.user)
        self.assertEqual(self.user.get_github_login(), "octocat")

    def test_uses_social_auth_when_only_source(self):
        from social_django.models import UserSocialAuth

        UserSocialAuth.objects.create(user=self.user, provider="github", uid="99", extra_data={"login": "ghuser"})
        self.assertEqual(self.user.get_github_login(), "ghuser")

    def test_uses_team_integration_when_only_source(self):
        Integration.objects.create(
            team=self.team,
            kind="github",
            integration_id="inst-1",
            config={"connecting_user_github_login": "teamuser"},
            sensitive_config={},
            created_by=self.user,
        )
        self.assertEqual(self.user.get_github_login(), "teamuser")

    def test_user_integration_takes_precedence_over_social_auth(self):
        from social_django.models import UserSocialAuth

        _create_user_integration(self.user)
        UserSocialAuth.objects.create(user=self.user, provider="github", uid="99", extra_data={"login": "ghuser"})
        self.assertEqual(self.user.get_github_login(), "octocat")

    def test_social_auth_takes_precedence_over_team_integration(self):
        from social_django.models import UserSocialAuth

        UserSocialAuth.objects.create(user=self.user, provider="github", uid="99", extra_data={"login": "ghuser"})
        Integration.objects.create(
            team=self.team,
            kind="github",
            integration_id="inst-1",
            config={"connecting_user_github_login": "teamuser"},
            sensitive_config={},
            created_by=self.user,
        )
        self.assertEqual(self.user.get_github_login(), "ghuser")


class TestUserGitHubIntegration(APIBaseTest):
    def _make_integration(self, **config_overrides) -> UserGitHubIntegration:
        now = int(time.time())
        config = {
            "github_user": {"login": "octocat", "id": 99},
            "user_token_refreshed_at": now,
            "user_access_token_expires_at": now + 28800,
            "user_refresh_token_expires_at": now + 15897600,
        }
        config.update(config_overrides)
        integration = UserIntegration.objects.create(
            user=self.user,
            kind="github",
            integration_id="12345",
            config=config,
            sensitive_config={
                "access_token": "ghs_install",
                "user_access_token": "gho_access",
                "user_refresh_token": "ghr_refresh",
            },
        )
        return UserGitHubIntegration(integration)

    def test_github_login_and_id(self):
        gh = self._make_integration()
        self.assertEqual(gh.github_login, "octocat")
        self.assertEqual(gh.github_id, 99)

    def test_user_access_token_expired_returns_true_past_halfway(self):
        now = int(time.time())
        gh = self._make_integration(
            user_token_refreshed_at=now - 20000,
            user_access_token_expires_at=now + 8800,
        )
        self.assertTrue(gh.user_access_token_expired())

    def test_user_access_token_expired_returns_false_when_fresh(self):
        gh = self._make_integration()
        self.assertFalse(gh.user_access_token_expired())

    @override_settings(GITHUB_APP_CLIENT_ID="client_id", GITHUB_APP_CLIENT_SECRET="client_secret")
    @patch("posthog.models.user_integration.requests.post")
    def test_refresh_user_access_token_updates_credentials(self, mock_post):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "access_token": "gho_new",
            "refresh_token": "ghr_new",
            "expires_in": 28800,
            "refresh_token_expires_in": 15897600,
        }
        mock_post.return_value = mock_response

        gh = self._make_integration()
        gh.refresh_user_access_token()

        gh.integration.refresh_from_db()
        self.assertEqual(gh.user_access_token, "gho_new")
        self.assertEqual(gh.user_refresh_token, "ghr_new")

    @override_settings(GITHUB_APP_CLIENT_ID="client_id", GITHUB_APP_CLIENT_SECRET="client_secret")
    @patch("posthog.models.user_integration.requests.post")
    def test_refresh_clears_expiry_metadata_when_github_omits_expiry_fields(self, mock_post):
        """Non-expiring tokens omit expires_in / refresh_token_expires_in; stale DB expiries must be cleared."""
        # https://app.graphite.com/github/pr/PostHog/posthog/55303#comment-PRRC_kwDODg-Tdc67nmop
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "access_token": "gho_non_expiring",
            "refresh_token": "ghr_rotated",
        }
        mock_post.return_value = mock_response

        now = int(time.time())
        gh = self._make_integration(
            user_token_refreshed_at=now - 20000,
            user_access_token_expires_at=now + 8800,
            user_refresh_token_expires_at=now - 1,
        )
        self.assertTrue(gh.user_access_token_expired())
        self.assertTrue(gh.user_refresh_token_expired())

        gh.refresh_user_access_token()
        gh.integration.refresh_from_db()

        self.assertNotIn("user_access_token_expires_at", gh.integration.config)
        self.assertNotIn("user_refresh_token_expires_at", gh.integration.config)
        self.assertFalse(gh.user_access_token_expired())
        self.assertFalse(gh.user_refresh_token_expired())

    @override_settings(GITHUB_APP_CLIENT_ID="client_id", GITHUB_APP_CLIENT_SECRET="client_secret")
    @patch("posthog.models.user_integration.requests.post")
    def test_refresh_discards_row_on_unrecoverable_error(self, mock_post):
        mock_response = MagicMock()
        mock_response.json.return_value = {"error": "bad_refresh_token"}
        mock_post.return_value = mock_response

        gh = self._make_integration()
        with self.assertRaises(ReauthorizationRequired):
            gh.refresh_user_access_token()
        self.assertFalse(UserIntegration.objects.filter(user=self.user, kind="github").exists())

    def test_get_usable_user_access_token_raises_when_refresh_token_expired(self):
        now = int(time.time())
        gh = self._make_integration(user_refresh_token_expires_at=now - 1)
        with self.assertRaises(ReauthorizationRequired):
            gh.get_usable_user_access_token()

    def test_get_usable_user_access_token_returns_cached_when_fresh(self):
        gh = self._make_integration()
        self.assertEqual(gh.get_usable_user_access_token(), "gho_access")

    @override_settings(GITHUB_APP_CLIENT_ID="client_id", GITHUB_APP_CLIENT_SECRET="client_secret")
    @patch("posthog.models.user_integration.requests.post")
    def test_get_usable_user_access_token_refreshes_when_expired(self, mock_post):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "access_token": "gho_refreshed",
            "refresh_token": "ghr_new",
            "expires_in": 28800,
            "refresh_token_expires_in": 15897600,
        }
        mock_post.return_value = mock_response

        now = int(time.time())
        gh = self._make_integration(
            user_token_refreshed_at=now - 20000,
            user_access_token_expires_at=now + 8800,
        )
        token = gh.get_usable_user_access_token()
        self.assertEqual(token, "gho_refreshed")

    def test_non_github_kind_raises_in_constructor(self):
        integration = UserIntegration.objects.create(
            user=self.user,
            kind="github",  # will override below
            integration_id="unused",
            config={},
            sensitive_config={},
        )
        integration.kind = "slack"
        with self.assertRaises(Exception, msg="non-github"):
            UserGitHubIntegration(integration)

    def test_user_refresh_token_expired_returns_false_when_no_expiry(self):
        gh = self._make_integration()
        gh.integration.config.pop("user_refresh_token_expires_at", None)
        gh.integration.save()
        self.assertFalse(gh.user_refresh_token_expired())


class TestUserGitHubIntegrationFromInstallation(APIBaseTest):
    def test_creates_integration_with_both_token_sets(self):
        integration = user_github_integration_from_installation(
            self.user,
            GitHubInstallationAccess(
                installation_id="12345",
                installation_info={"account": {"type": "User", "login": "octocat"}},
                access_token="ghs_install",
                token_expires_at="2099-01-01T00:00:00Z",
                repository_selection="selected",
            ),
            _authorization(),
        )

        self.assertEqual(integration.user, self.user)
        self.assertEqual(integration.kind, "github")
        self.assertEqual(integration.integration_id, "12345")
        self.assertEqual(integration.config["github_user"]["login"], "octocat")
        self.assertEqual(integration.sensitive_config["access_token"], "ghs_install")
        self.assertEqual(integration.sensitive_config["user_access_token"], "gho_access")
        self.assertEqual(integration.sensitive_config["user_refresh_token"], "ghr_refresh")

    def test_different_installation_creates_second_integration(self):
        _create_user_integration(self.user)
        integration = user_github_integration_from_installation(
            self.user,
            GitHubInstallationAccess(
                installation_id="67890",
                installation_info={"account": {"type": "Organization", "login": "posthog"}},
                access_token="ghs_new",
                token_expires_at="2099-01-01T00:00:00Z",
                repository_selection="all",
            ),
            GitHubUserAuthorization(
                gh_id=99,
                gh_login="octocat",
                access_token="gho_new",
                refresh_token="ghr_new",
                access_token_expires_in=28800,
                refresh_token_expires_in=15897600,
            ),
        )

        self.assertEqual(UserIntegration.objects.filter(user=self.user, kind="github").count(), 2)
        self.assertEqual(integration.integration_id, "67890")
        self.assertEqual(integration.sensitive_config["user_access_token"], "gho_new")

    def test_same_installation_updates_existing_integration(self):
        _create_user_integration(self.user, integration_id="12345")
        integration = user_github_integration_from_installation(
            self.user,
            GitHubInstallationAccess(
                installation_id="12345",
                installation_info={"account": {"type": "User", "login": "octocat"}},
                access_token="ghs_refreshed",
                token_expires_at="2099-01-01T00:00:00Z",
                repository_selection="all",
            ),
            GitHubUserAuthorization(
                gh_id=99,
                gh_login="octocat",
                access_token="gho_refreshed",
                refresh_token="ghr_refreshed",
                access_token_expires_in=28800,
                refresh_token_expires_in=15897600,
            ),
        )

        self.assertEqual(UserIntegration.objects.filter(user=self.user, kind="github").count(), 1)
        self.assertEqual(integration.integration_id, "12345")
        self.assertEqual(integration.sensitive_config["user_access_token"], "gho_refreshed")


class TestGithubUserFromCode(APIBaseTest):
    @patch("posthog.models.integration.requests.get")
    @patch("posthog.models.integration.requests.post")
    @override_settings(GITHUB_APP_CLIENT_ID="client_id", GITHUB_APP_CLIENT_SECRET="client_secret")
    def test_returns_full_authorization_including_tokens(self, mock_post, mock_get):
        mock_post.return_value = MagicMock(
            json=lambda: {
                "access_token": "gho_user_token",
                "refresh_token": "ghr_user_refresh",
                "expires_in": 28800,
                "refresh_token_expires_in": 15897600,
            }
        )
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"id": 42, "login": "testuser"},
        )

        from posthog.models.integration import GitHubIntegration

        result = GitHubIntegration.github_user_from_code("test_code")
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.gh_id, 42)
        self.assertEqual(result.gh_login, "testuser")
        self.assertEqual(result.access_token, "gho_user_token")
        self.assertEqual(result.refresh_token, "ghr_user_refresh")
        self.assertEqual(result.access_token_expires_in, 28800)
        self.assertEqual(result.refresh_token_expires_in, 15897600)
