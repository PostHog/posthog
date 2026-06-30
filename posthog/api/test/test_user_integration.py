import time
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.test import override_settings

from parameterized import parameterized
from rest_framework import status

from posthog.api.github_callback.state import (
    load_authorize_state,
    parse_github_authorize_state_param,
    store_unified_authorize_state,
)
from posthog.api.github_callback.types import FlowKind, GitHubAuthorizeState
from posthog.models import OrganizationMembership, User
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

    @patch("posthog.api.user_integration.UserGitHubIntegration.uninstall_app_installation")
    def test_delete_last_reference_calls_github_uninstall(self, mock_uninstall):
        mock_uninstall.return_value = True
        _create_user_integration(self.user, integration_id="12345")

        response = self.client.delete("/api/users/@me/integrations/github/12345/")

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        mock_uninstall.assert_called_once_with("12345")
        self.assertFalse(UserIntegration.objects.filter(integration_id="12345").exists())

    @patch("posthog.api.user_integration.UserGitHubIntegration.uninstall_app_installation")
    def test_delete_skips_uninstall_when_team_reference_exists(self, mock_uninstall):
        _create_user_integration(self.user, integration_id="12345")
        Integration.objects.create(
            team=self.team, kind="github", integration_id="12345", config={}, sensitive_config={}
        )

        response = self.client.delete("/api/users/@me/integrations/github/12345/")

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        mock_uninstall.assert_not_called()
        self.assertFalse(UserIntegration.objects.filter(user=self.user, integration_id="12345").exists())

    @patch("posthog.api.user_integration.UserGitHubIntegration.uninstall_app_installation")
    def test_delete_skips_uninstall_when_other_user_reference_exists(self, mock_uninstall):
        other_user = User.objects.create_and_join(self.organization, "other@posthog.com", "password")
        _create_user_integration(self.user, integration_id="12345")
        _create_user_integration(other_user, integration_id="12345")

        response = self.client.delete("/api/users/@me/integrations/github/12345/")

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        mock_uninstall.assert_not_called()

    @patch(
        "posthog.api.user_integration.UserGitHubIntegration.uninstall_if_last_reference",
        side_effect=Exception("GitHub API error"),
    )
    def test_delete_still_returns_204_when_uninstall_fails(self, _mock_uninstall):
        _create_user_integration(self.user, integration_id="12345")

        response = self.client.delete("/api/users/@me/integrations/github/12345/")

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(UserIntegration.objects.filter(integration_id="12345").exists())

    @override_settings(GITHUB_APP_CLIENT_ID="client_id")
    @patch(
        "posthog.api.github_callback.types.get_instance_settings",
        return_value={"GITHUB_APP_SLUG": "posthog-dev"},
    )
    def test_github_start_returns_install_url_when_no_team_github(self, _mock_settings):
        response = self.client.post("/api/users/@me/integrations/github/start/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertIn("install_url", data)
        self.assertEqual(data.get("connect_flow"), "app_install")
        self.assertIn("github.com/apps/posthog-dev/installations/new", data["install_url"])

    @override_settings(
        GITHUB_APP_CLIENT_ID="gh_client_123", SITE_URL="https://us.posthog.com", GITHUB_APP_CLIENT_SECRET="s"
    )
    def test_github_start_returns_oauth_discover_url_for_posthog_code_without_team_github(self):
        response = self.client.post(
            "/api/users/@me/integrations/github/start/",
            {"team_id": self.team.id, "connect_from": "posthog_code"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertIn("install_url", data)
        self.assertEqual(data.get("connect_flow"), "oauth_discover")
        url = data["install_url"]
        self.assertIn("github.com/login/oauth/authorize", url)
        self.assertIn("client_id=gh_client_123", url)
        self.assertIn("redirect_uri=https%3A%2F%2Fus.posthog.com%2Fcomplete%2Fgithub-link%2F", url)

    @override_settings(GITHUB_APP_CLIENT_ID="gh_client_123", SITE_URL="https://us.posthog.com")
    def test_github_start_web_fast_path_returns_oauth_url_when_team_has_github_integration(self):
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
        self.assertEqual(data.get("connect_flow"), "oauth_authorize")
        url = data["install_url"]
        self.assertIn("github.com/login/oauth/authorize", url)
        self.assertIn("client_id=gh_client_123", url)
        self.assertIn("redirect_uri=https%3A%2F%2Fus.posthog.com%2Fcomplete%2Fgithub-link%2F", url)

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
        "posthog.api.github_callback.types.get_instance_settings",
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
        "posthog.api.github_callback.types.get_instance_settings",
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
            "posthog.api.github_callback.types.get_instance_settings",
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
        store_unified_authorize_state(
            GitHubAuthorizeState(
                token=state,
                flow=FlowKind.PERSONAL_OAUTH,
                user_id=self.user.id,
                installation_id="12345",
            ),
        )

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

    @override_settings(
        GITHUB_APP_CLIENT_ID="client_id",
        GITHUB_APP_CLIENT_SECRET="client_secret",
        SITE_URL="https://us.posthog.com",
    )
    @patch("posthog.api.user_integration.requests.get")
    @patch("posthog.models.integration.GitHubIntegration.client_request")
    @patch("posthog.models.integration.GitHubIntegration.github_user_from_code")
    def test_github_link_oauth_callback_ignores_query_installation_id_when_state_binds_one(
        self, mock_user_from_code, mock_client_request, mock_verify_get
    ):
        # PERSONAL_OAUTH binds ``installation_id`` in the authorize cache. A
        # tampered ``installation_id`` query param must not steer the resulting
        # UserIntegration to a different installation.
        mock_verify_get.return_value = MagicMock(status_code=200)
        mock_user_from_code.return_value = _authorization()
        mock_install_info = MagicMock()
        mock_install_info.json.return_value = {"account": {"type": "User", "login": "octocat"}}
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
        state = "tok_oauth_mismatch"
        store_unified_authorize_state(
            GitHubAuthorizeState(
                token=state,
                flow=FlowKind.PERSONAL_OAUTH,
                user_id=self.user.id,
                installation_id="12345",
            ),
        )
        state_q = urlencode({"token": state, "source": "user_integration"})

        response = self.client.get(
            "/complete/github-link/",
            {"code": "test_code", "state": state_q, "installation_id": "999"},
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn("github_link_success=1", response["Location"])
        self.assertTrue(UserIntegration.objects.filter(user=self.user, integration_id="12345").exists())
        self.assertFalse(UserIntegration.objects.filter(integration_id="999").exists())
        # The installation-access check went against the cached id, not the query one.
        verify_url = mock_verify_get.call_args[0][0]
        self.assertIn("/installations/12345/repositories", verify_url)
        self.assertNotIn("/installations/999/repositories", verify_url)

    @override_settings(
        GITHUB_APP_CLIENT_ID="client_id",
        GITHUB_APP_CLIENT_SECRET="client_secret",
        SITE_URL="https://us.posthog.com",
    )
    @patch("posthog.api.user_integration.requests.get")
    @patch("posthog.models.integration.GitHubIntegration.client_request")
    @patch("posthog.models.integration.GitHubIntegration.github_user_from_code")
    def test_github_link_oauth_discover_creates_user_integration_from_visible_installation(
        self, mock_user_from_code, mock_client_request, mock_requests_get
    ):
        mock_user_from_code.return_value = _authorization()
        mock_requests_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"installations": [{"id": 12345}]},
        )
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

        state = "tok_oauth_discover_123"
        store_unified_authorize_state(
            GitHubAuthorizeState(
                token=state,
                flow=FlowKind.OAUTH_DISCOVER,
                user_id=self.user.id,
                connect_from="posthog_code",
            ),
        )

        response = self.client.get(
            "/complete/github-link/",
            {"code": "test_code", "state": state},
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn("/account-connected/github-integration", response["Location"])
        mock_user_from_code.assert_called_once_with(
            "test_code", redirect_uri="https://us.posthog.com/complete/github-link/"
        )

        integration = UserIntegration.objects.get(user=self.user, kind="github")
        self.assertEqual(integration.integration_id, "12345")

    @override_settings(
        GITHUB_APP_CLIENT_ID="client_id",
        GITHUB_APP_CLIENT_SECRET="client_secret",
        SITE_URL="https://us.posthog.com",
    )
    @patch(
        "posthog.api.github_callback.types.get_instance_settings",
        return_value={"GITHUB_APP_SLUG": "posthog-dev"},
    )
    @patch("posthog.api.user_integration.requests.get")
    @patch("posthog.models.integration.GitHubIntegration.github_user_from_code")
    def test_github_link_oauth_discover_redirects_to_app_install_when_no_installations(
        self, mock_user_from_code, mock_requests_get, _mock_settings
    ):
        mock_user_from_code.return_value = _authorization()
        mock_requests_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"installations": []},
        )

        state = "tok_oauth_discover_empty"
        store_unified_authorize_state(
            GitHubAuthorizeState(
                token=state,
                flow=FlowKind.OAUTH_DISCOVER,
                user_id=self.user.id,
                connect_from="posthog_code",
            ),
        )

        response = self.client.get(
            "/complete/github-link/",
            {"code": "test_code", "state": state},
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn("github.com/apps/posthog-dev/installations/new", response["Location"])

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
        store_unified_authorize_state(
            GitHubAuthorizeState(token=state, flow=FlowKind.PERSONAL_INSTALL, user_id=self.user.id),
        )

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

    @parameterized.expand(
        [
            ("posthog_code", "/account-connected/github-integration"),
            ("posthog_mobile", "posthog://github/callback"),
        ]
    )
    @override_settings(GITHUB_APP_CLIENT_ID="client_id", GITHUB_APP_CLIENT_SECRET="client_secret")
    @patch("posthog.api.user_integration.requests.get")
    @patch("posthog.models.integration.GitHubIntegration.client_request")
    @patch("posthog.models.integration.GitHubIntegration.github_user_from_code")
    def test_github_link_redirects_to_client_destination_on_success(
        self,
        connect_from,
        expected_destination,
        mock_user_from_code,
        mock_client_request,
        mock_verify_get,
    ):
        """First-party clients pass ``connect_from`` via start payload → cache; success redirects to their destination."""
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

        state = f"test_state_{connect_from}"
        store_unified_authorize_state(
            GitHubAuthorizeState(
                token=state,
                flow=FlowKind.PERSONAL_INSTALL,
                user_id=self.user.id,
                connect_from=connect_from,
            ),
        )

        response = self.client.get(
            "/complete/github-link/",
            {"installation_id": "12345", "code": "test_code", "state": state},
        )

        self.assertEqual(response.status_code, 302)
        loc = response["Location"]
        self.assertIn(expected_destination, loc)
        self.assertIn("provider=github", loc)
        self.assertNotIn("error=", loc)

    def test_github_link_redirects_to_mobile_deep_link_with_error(self):
        """When GitHub returns an error, the mobile deep link still carries provider + error."""
        state = "test_state_posthog_mobile_error"
        store_unified_authorize_state(
            GitHubAuthorizeState(
                token=state,
                flow=FlowKind.PERSONAL_INSTALL,
                user_id=self.user.id,
                connect_from="posthog_mobile",
            ),
        )

        response = self.client.get(
            "/complete/github-link/",
            {"error": "access_denied", "state": state},
        )

        self.assertEqual(response.status_code, 302)
        loc = response["Location"]
        self.assertIn("posthog://github/callback", loc)
        self.assertIn("provider=github", loc)
        self.assertIn("error=access_denied", loc)

    def test_github_link_callback_rejects_mismatched_state(self):
        store_unified_authorize_state(
            GitHubAuthorizeState(token="valid_state", flow=FlowKind.PERSONAL_INSTALL, user_id=self.user.id),
        )
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

    @override_settings(GITHUB_APP_CLIENT_ID="client_id", SITE_URL="https://us.posthog.com")
    def test_github_link_personal_install_without_code_recovers_via_oauth_discover(self):
        # GitHub omits the OAuth code when the App is already installed, returning a
        # setup update (installation_id, setup_action=update) instead. The callback
        # must bounce through OAuth-discover to obtain a code rather than erroring.
        store_unified_authorize_state(
            GitHubAuthorizeState(
                token="tok_already_installed",
                flow=FlowKind.PERSONAL_INSTALL,
                user_id=self.user.id,
                connect_from="posthog_code",
            ),
        )

        response = self.client.get(
            "/complete/github-link/",
            {"installation_id": "75826265", "setup_action": "update", "state": "token=tok_already_installed"},
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn("github.com/login/oauth/authorize", response["Location"])

        discover_state_param = parse_qs(urlparse(response["Location"]).query)["state"][0]
        discover_token, _ = parse_github_authorize_state_param(discover_state_param)
        assert discover_token is not None
        discover_state = load_authorize_state(discover_token, user_id=self.user.id)
        assert discover_state is not None
        self.assertEqual(discover_state.flow, FlowKind.OAUTH_DISCOVER)
        self.assertEqual(discover_state.connect_from, "posthog_code")

    @override_settings(GITHUB_APP_CLIENT_ID="client_id", GITHUB_APP_CLIENT_SECRET="client_secret")
    @patch("posthog.models.integration.GitHubIntegration.integration_from_installation_id")
    @patch("posthog.api.user_integration.requests.get")
    @patch("posthog.models.integration.GitHubIntegration.client_request")
    @patch("posthog.models.integration.GitHubIntegration.github_user_from_code")
    def test_github_link_callback_team_oauth_authorize_creates_team_integration(
        self,
        mock_user_from_code,
        mock_client_request,
        mock_verify_get,
        mock_integration_from_install,
    ):
        # Verify-access call returns 200 → user has access to the installation.
        mock_verify_get.return_value = MagicMock(status_code=200)
        mock_user_from_code.return_value = _authorization()
        mock_install_info = MagicMock()
        mock_install_info.json.return_value = {"account": {"type": "Organization", "login": "acme"}}
        mock_access_token = MagicMock()
        mock_access_token.json.return_value = {
            "token": "ghs_install_token",
            "expires_at": "2099-01-01T00:00:00Z",
            "repository_selection": "all",
        }
        mock_client_request.side_effect = [mock_install_info, mock_access_token]

        # Writing a team integration requires admin-level access.
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        team_integration = Integration.objects.create(
            team=self.team,
            kind="github",
            integration_id="12345",
            config={"installation_id": "12345"},
            sensitive_config={"access_token": "ghs_install_token"},
            created_by=self.user,
        )
        mock_integration_from_install.return_value = team_integration

        state = "tok_team_oauth_123"
        store_unified_authorize_state(
            GitHubAuthorizeState(
                token=state,
                flow=FlowKind.TEAM_OAUTH,
                user_id=self.user.id,
                team_id=self.team.pk,
                installation_id="12345",
                next_url="/project/{}/integrations/github".format(self.team.pk),
            ),
        )

        response = self.client.get(
            "/complete/github-link/",
            {"code": "test_code", "state": state},
        )

        self.assertEqual(response.status_code, 302)
        # Used the OAuth-flow redirect URI so the code exchange matches GitHub's expectation.
        mock_user_from_code.assert_called_once()
        _, kwargs = mock_user_from_code.call_args
        self.assertTrue(kwargs.get("redirect_uri", "").endswith("/complete/github-link/"))
        mock_integration_from_install.assert_called_once_with("12345", self.team.pk, self.user)
        # Redirected back to the requested ``next`` URL with the install/integration ids appended.
        location = response["Location"]
        self.assertIn(f"/project/{self.team.pk}/integrations/github", location)
        self.assertIn("installation_id=12345", location)
        self.assertIn(f"integration_id={team_integration.id}", location)


class TestGetGithubLoginPrecedence(APIBaseTest):
    """User.get_github_login() precedence: UserIntegration > UserSocialAuth > team-level GitHub Integration."""

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


def _create_slack_user_integration(
    user: User,
    *,
    slack_user_id: str = "U999",
    slack_team_id: str = "T12345",
    slack_team_name: str | None = "Test Workspace",
    slack_email_at_link: str | None = "dev@example.com",
) -> UserIntegration:
    return UserIntegration.objects.create(
        user=user,
        kind=UserIntegration.IntegrationKind.SLACK,
        integration_id=slack_user_id,
        config={
            "slack_team_id": slack_team_id,
            "slack_team_name": slack_team_name,
            "slack_email_at_link": slack_email_at_link,
            "linked_at": int(time.time()),
        },
        sensitive_config={},
    )


class TestUserIntegrationKindParam(APIBaseTest):
    """Back-compat + dispatch behavior of the unified list endpoint."""

    def test_default_kind_returns_github_rows(self):
        # Mobile + Code SDK call this URL without a query param and rely on
        # receiving GitHub-shaped items. Don't change the default lightly.
        _create_user_integration(self.user)  # github
        response = self.client.get("/api/users/@me/integrations/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.json()["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["installation_id"], "12345")

    def test_explicit_github_kind_matches_default(self):
        _create_user_integration(self.user)
        default_response = self.client.get("/api/users/@me/integrations/")
        explicit_response = self.client.get("/api/users/@me/integrations/?kind=github")
        self.assertEqual(default_response.json(), explicit_response.json())

    def test_unsupported_kind_returns_400(self):
        response = self.client.get("/api/users/@me/integrations/?kind=bitbucket")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class TestUserIntegrationSlackEndpoints(APIBaseTest):
    def test_slack_list_returns_empty_when_no_links(self):
        response = self.client.get("/api/users/@me/integrations/?kind=slack")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["results"], [])

    def test_slack_list_returns_user_link_with_full_payload(self):
        _create_slack_user_integration(self.user)
        response = self.client.get("/api/users/@me/integrations/?kind=slack")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.json()["results"]
        self.assertEqual(len(results), 1)
        row = results[0]
        self.assertEqual(row["kind"], "slack")
        self.assertEqual(row["slack_user_id"], "U999")
        self.assertEqual(row["slack_team_id"], "T12345")
        self.assertEqual(row["slack_team_name"], "Test Workspace")
        self.assertEqual(row["slack_email_at_link"], "dev@example.com")

    def test_slack_list_does_not_include_github_rows(self):
        _create_user_integration(self.user)
        _create_slack_user_integration(self.user)
        response = self.client.get("/api/users/@me/integrations/?kind=slack")
        results = response.json()["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["kind"], "slack")

    def test_slack_list_scoped_to_requesting_user(self):
        other = User.objects.create(email="other@example.com", distinct_id="other-1")
        _create_slack_user_integration(other, slack_user_id="U-OTHER")
        response = self.client.get("/api/users/@me/integrations/?kind=slack")
        self.assertEqual(response.json()["results"], [])

    def test_slack_destroy_removes_row(self):
        _create_slack_user_integration(self.user, slack_user_id="U999")
        response = self.client.delete("/api/users/@me/integrations/slack/U999/")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(
            UserIntegration.objects.filter(
                user=self.user, kind=UserIntegration.IntegrationKind.SLACK, integration_id="U999"
            ).exists()
        )

    def test_slack_destroy_404_when_link_missing(self):
        response = self.client.delete("/api/users/@me/integrations/slack/U-NOPE/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_slack_destroy_cannot_remove_other_users_link(self):
        other = User.objects.create(email="other@example.com", distinct_id="other-2")
        _create_slack_user_integration(other, slack_user_id="U-OTHER")
        # The requesting user has no row with this slack_user_id, so we get 404,
        # not 403 — the route refuses to acknowledge another user's rows.
        response = self.client.delete("/api/users/@me/integrations/slack/U-OTHER/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertTrue(
            UserIntegration.objects.filter(
                user=other, kind=UserIntegration.IntegrationKind.SLACK, integration_id="U-OTHER"
            ).exists()
        )

    def _enable_flag(self) -> Any:
        return patch("posthog.api.user_integration.slack_oauth_link_enabled", return_value=True)

    def _seed_workspace_integration(self) -> Integration:
        return Integration.objects.create(
            team=self.team,
            kind="slack",
            integration_id="T12345",
            sensitive_config={"access_token": "xoxb-test"},
        )

    def test_slack_start_returns_install_url_when_workspace_connected(self):
        self._seed_workspace_integration()
        with self._enable_flag():
            response = self.client.post("/api/users/@me/integrations/slack/start/", data={}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        install_url = response.json()["install_url"]
        # Routes through the same backend authorize entry — settings is just
        # another invite origin, not a separate OAuth flow.
        self.assertIn("/complete/slack-link/start/?state=", install_url)

    def test_slack_start_fails_when_no_workspace_integration(self):
        with self._enable_flag():
            response = self.client.post("/api/users/@me/integrations/slack/start/", data={}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("no Slack workspace", response.json()["detail"])

    def test_slack_start_fails_when_already_linked(self):
        self._seed_workspace_integration()
        _create_slack_user_integration(self.user, slack_team_id="T12345")
        with self._enable_flag():
            response = self.client.post("/api/users/@me/integrations/slack/start/", data={}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("already linked", response.json()["detail"])

    def test_slack_start_403_when_flag_off(self):
        self._seed_workspace_integration()
        with patch("posthog.api.user_integration.slack_oauth_link_enabled", return_value=False):
            response = self.client.post("/api/users/@me/integrations/slack/start/", data={}, format="json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_slack_linkable_empty_when_no_workspaces_connected(self):
        with self._enable_flag():
            response = self.client.get("/api/users/@me/integrations/slack/linkable_workspaces/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["results"], [])

    def test_slack_linkable_returns_workspaces_user_can_still_link(self):
        self._seed_workspace_integration()
        with self._enable_flag():
            response = self.client.get("/api/users/@me/integrations/slack/linkable_workspaces/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.json()["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["slack_team_id"], "T12345")
        self.assertEqual(results[0]["posthog_team_id"], self.team.id)

    def test_slack_linkable_excludes_workspaces_user_already_linked(self):
        self._seed_workspace_integration()
        _create_slack_user_integration(self.user, slack_team_id="T12345")
        with self._enable_flag():
            response = self.client.get("/api/users/@me/integrations/slack/linkable_workspaces/")
        # The screenshot bug: user has linked the only workspace, so the
        # picker has nothing to offer. Frontend uses the empty list to hide
        # the "Link another workspace" button instead of letting the user
        # attempt a duplicate link the backend would reject.
        self.assertEqual(response.json()["results"], [])

    def test_slack_linkable_skips_workspaces_with_flag_off(self):
        self._seed_workspace_integration()
        with patch("posthog.api.user_integration.slack_oauth_link_enabled", return_value=False):
            response = self.client.get("/api/users/@me/integrations/slack/linkable_workspaces/")
        self.assertEqual(response.json()["results"], [])

    def test_slack_linkable_excludes_private_project_user_cannot_access(self):
        # The endpoint scopes candidates by organization, but org membership
        # alone is not access — an access-control-enabled project the user
        # has no role in must not surface its Slack workspace metadata
        # (workspace id, team name) in the picker. Without the per-team
        # ``effective_membership_level`` filter, an org member could call this
        # endpoint and enumerate Slack installs (plus project + organization
        # names) for every private project in their orgs.
        from posthog.constants import AvailableFeature
        from posthog.models.organization import Organization, OrganizationMembership
        from posthog.models.team import Team

        from ee.models.rbac.access_control import AccessControl

        ac_org = Organization.objects.create(name="AC Org")
        # ``pre_save`` on Organization resets ``available_product_features`` on
        # insert; set it after the initial save to opt the org into per-team
        # access-control checks.
        ac_org.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        ac_org.save()
        private_team = Team.objects.create(organization=ac_org, name="Private Team")
        AccessControl.objects.create(
            team=private_team,
            resource="project",
            resource_id=str(private_team.id),
            organization_member=None,
            role=None,
            access_level="none",
        )
        OrganizationMembership.objects.create(organization=ac_org, user=self.user)
        Integration.objects.create(
            team=private_team,
            kind="slack",
            integration_id="T-PRIVATE",
            sensitive_config={"access_token": "xoxb-private"},
        )

        with self._enable_flag():
            response = self.client.get("/api/users/@me/integrations/slack/linkable_workspaces/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.json()["results"]
        self.assertNotIn("T-PRIVATE", [r["slack_team_id"] for r in results])

    def test_slack_start_with_explicit_slack_team_id_links_against_picked_workspace(self):
        self._seed_workspace_integration()
        with self._enable_flag():
            response = self.client.post(
                "/api/users/@me/integrations/slack/start/",
                data={"team_id": self.team.id, "slack_team_id": "T12345"},
                format="json",
            )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("/complete/slack-link/start/?state=", response.json()["install_url"])

    def test_slack_start_with_explicit_unknown_slack_team_id_is_400(self):
        self._seed_workspace_integration()
        with self._enable_flag():
            response = self.client.post(
                "/api/users/@me/integrations/slack/start/",
                data={"team_id": self.team.id, "slack_team_id": "T-NOPE"},
                format="json",
            )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
