from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.core.cache import cache
from django.test import override_settings
from django.utils import timezone

from rest_framework import status
from social_core.exceptions import AuthFailed
from social_django.models import UserSocialAuth

from posthog.models import OrganizationDomain, User
from posthog.models.organization import OrganizationMembership
from posthog.models.user_social_identity import (
    UserSocialIdentity,
    available_providers_for_user,
    can_disconnect_provider,
    can_user_enable_login_for,
)

from ee.api.authentication import social_auth_allowed


class TestHelpers(APIBaseTest):
    def test_can_user_enable_login_respects_sso_enforcement(self):
        self.assertTrue(can_user_enable_login_for(self.user, "github"))
        self._enforce_sso("google-oauth2")
        self.assertFalse(can_user_enable_login_for(self.user, "github"))
        self.assertTrue(can_user_enable_login_for(self.user, "google-oauth2"))

    def test_available_providers_includes_github_under_sso_enforcement(self):
        with patch(
            "posthog.models.user_social_identity.get_instance_available_sso_providers",
            return_value={"google-oauth2": True, "github": True, "gitlab": True},
        ):
            self.assertEqual(set(available_providers_for_user(self.user)), {"google-oauth2", "github", "gitlab"})
            self._enforce_sso("google-oauth2")
            self.assertEqual(available_providers_for_user(self.user), ["google-oauth2", "github"])

    def test_available_providers_under_github_enforcement_no_duplicate(self):
        with patch(
            "posthog.models.user_social_identity.get_instance_available_sso_providers",
            return_value={"google-oauth2": True, "github": True, "gitlab": True},
        ):
            self._enforce_sso("github")
            self.assertEqual(available_providers_for_user(self.user), ["github"])

    def test_can_disconnect_blocks_enforced_provider(self):
        self._enforce_sso("google-oauth2")
        self.assertFalse(can_disconnect_provider(self.user, "google-oauth2"))
        self.assertTrue(can_disconnect_provider(self.user, "github"))

    def _enforce_sso(self, sso_enforcement: str) -> None:
        self.organization.available_product_features = [
            {"key": "sso_enforcement", "name": "SSO enforcement"},
            {"key": "google_login", "name": "Google"},
        ]
        self.organization.save()
        OrganizationDomain.objects.create(
            organization=self.organization,
            domain=self.user.email.split("@")[1],
            verified_at=timezone.now(),
            sso_enforcement=sso_enforcement,
        )
        patcher = patch(
            "posthog.models.organization_domain.get_instance_available_sso_providers",
            return_value={"google-oauth2": True, "github": True, "gitlab": True},
        )
        patcher.start()
        self.addCleanup(patcher.stop)


class TestLinkedAccountsEndpoints(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)
        self._providers_patcher = patch(
            "posthog.models.user_social_identity.get_instance_available_sso_providers",
            return_value={"google-oauth2": True, "github": True, "gitlab": False},
        )
        self._providers_patcher.start()
        self.addCleanup(self._providers_patcher.stop)

    def _enforce_sso(self, sso_enforcement: str) -> None:
        self.organization.available_product_features = [
            {"key": "sso_enforcement", "name": "SSO enforcement"},
            {"key": "google_login", "name": "Google"},
        ]
        self.organization.save()
        OrganizationDomain.objects.create(
            organization=self.organization,
            domain=self.user.email.split("@")[1],
            verified_at=timezone.now(),
            sso_enforcement=sso_enforcement,
        )
        patcher = patch(
            "posthog.models.organization_domain.get_instance_available_sso_providers",
            return_value={"google-oauth2": True, "github": True, "gitlab": True, "saml": True},
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    # ── List ──

    def test_list_returns_row_for_each_configured_provider(self):
        response = self.client.get("/api/linked_accounts/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.json()["results"]
        providers = {r["provider"]: r for r in results}
        self.assertEqual(set(providers.keys()), {"google-oauth2", "github"})
        self.assertFalse(providers["google-oauth2"]["connected"])
        self.assertEqual(providers["google-oauth2"]["connect_flow"], "social_login")
        self.assertFalse(providers["github"]["connected"])
        self.assertEqual(providers["github"]["connect_flow"], "github_link")

    def test_list_shows_identity_only_connection(self):
        UserSocialIdentity.objects.create(
            user=self.user, provider="github", uid="42", extra_data={"login": "octo", "id": 42}
        )
        results = self.client.get("/api/linked_accounts/").json()["results"]
        gh = next(r for r in results if r["provider"] == "github")
        self.assertTrue(gh["connected"])
        self.assertEqual(gh["account_identifier"], "octo")
        self.assertFalse(gh["login_enabled"])
        self.assertTrue(gh["can_disconnect"])

    def test_list_shows_login_enabled_via_social_auth(self):
        # Backward compat: UserSocialAuth without UserSocialIdentity → connected + login_enabled.
        UserSocialAuth.objects.create(
            user=self.user, provider="github", uid="42", extra_data={"login": "octo", "id": 42}
        )
        results = self.client.get("/api/linked_accounts/").json()["results"]
        gh = next(r for r in results if r["provider"] == "github")
        self.assertTrue(gh["connected"])
        self.assertTrue(gh["login_enabled"])

    def test_list_shows_enforced_provider_plus_github_when_sso_enforced(self):
        self._enforce_sso("google-oauth2")
        body = self.client.get("/api/linked_accounts/").json()
        providers = {r["provider"]: r for r in body["results"]}
        self.assertEqual(set(providers.keys()), {"google-oauth2", "github"})
        self.assertFalse(providers["github"]["can_enable_login"])
        self.assertEqual(providers["github"]["connect_flow"], "github_link")
        self.assertEqual(body["sso_enforcement"], "google-oauth2")
        self.assertEqual(body["sso_enforcement_provider_name"], "Google")

    def test_list_reports_no_enforcement_when_unenforced(self):
        body = self.client.get("/api/linked_accounts/").json()
        self.assertIsNone(body["sso_enforcement"])
        self.assertIsNone(body["sso_enforcement_provider_name"])

    def test_list_surfaces_stray_historical_social_auth_rows(self):
        UserSocialAuth.objects.create(user=self.user, provider="gitlab", uid="42", extra_data={"username": "u"})
        providers = {r["provider"]: r for r in self.client.get("/api/linked_accounts/").json()["results"]}
        self.assertIn("gitlab", providers)
        self.assertTrue(providers["gitlab"]["connected"])
        self.assertTrue(providers["gitlab"]["login_enabled"])

    def test_list_surfaces_stray_historical_identity_rows(self):
        UserSocialIdentity.objects.create(user=self.user, provider="gitlab", uid="42", extra_data={"username": "u"})
        providers = {r["provider"]: r for r in self.client.get("/api/linked_accounts/").json()["results"]}
        self.assertIn("gitlab", providers)
        self.assertTrue(providers["gitlab"]["connected"])
        self.assertFalse(providers["gitlab"]["login_enabled"])

    def test_list_does_not_offer_connect_for_saml(self):
        with patch(
            "posthog.models.user_social_identity.get_instance_available_sso_providers",
            return_value={"google-oauth2": False, "github": False, "gitlab": False, "saml": True},
        ):
            self._enforce_sso("saml")
            results = self.client.get("/api/linked_accounts/").json()["results"]
            saml = next(r for r in results if r["provider"] == "saml")
            self.assertIsNone(saml["connect_flow"])
            self.assertIsNone(saml["connect_path"])

    # ── PATCH (toggle login) ──

    def test_patch_enable_login_creates_social_auth(self):
        UserSocialIdentity.objects.create(user=self.user, provider="github", uid="42", extra_data={"login": "octo"})
        response = self.client.patch(
            "/api/linked_accounts/github/",
            {"login_enabled": True},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.json()["login_enabled"])
        self.assertTrue(UserSocialAuth.objects.filter(user=self.user, provider="github", uid="42").exists())

    def test_patch_enable_login_rejects_when_another_user_has_login(self):
        other = User.objects.create_and_join(self.organization, "other@example.com", "x")
        UserSocialAuth.objects.create(user=other, provider="github", uid="42", extra_data={"login": "octo"})
        UserSocialIdentity.objects.create(user=self.user, provider="github", uid="42", extra_data={"login": "octo"})
        response = self.client.patch(
            "/api/linked_accounts/github/",
            {"login_enabled": True},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(UserSocialAuth.objects.filter(user=self.user, provider="github").exists())

    def test_patch_disable_login_backfills_identity_and_deletes_social_auth(self):
        # Backward compat: user only has UserSocialAuth (pre-feature). Disabling login
        # should create a UserSocialIdentity and delete the UserSocialAuth.
        UserSocialAuth.objects.create(user=self.user, provider="github", uid="42", extra_data={"login": "octo"})
        response = self.client.patch(
            "/api/linked_accounts/github/",
            {"login_enabled": False},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.json()["login_enabled"])
        self.assertTrue(response.json()["connected"])
        self.assertFalse(UserSocialAuth.objects.filter(user=self.user, provider="github").exists())
        identity = UserSocialIdentity.objects.get(user=self.user, provider="github")
        self.assertEqual(identity.uid, "42")
        self.assertEqual(identity.extra_data["login"], "octo")

    def test_patch_disable_login_keeps_existing_identity(self):
        UserSocialIdentity.objects.create(user=self.user, provider="github", uid="42", extra_data={"login": "octo"})
        UserSocialAuth.objects.create(user=self.user, provider="github", uid="42", extra_data={"login": "octo"})
        response = self.client.patch(
            "/api/linked_accounts/github/",
            {"login_enabled": False},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(UserSocialAuth.objects.filter(user=self.user, provider="github").exists())
        self.assertTrue(UserSocialIdentity.objects.filter(user=self.user, provider="github").exists())

    def test_patch_rejects_enable_when_sso_enforcement_blocks(self):
        self._enforce_sso("google-oauth2")
        UserSocialIdentity.objects.create(user=self.user, provider="github", uid="42", extra_data={"login": "octo"})
        response = self.client.patch(
            "/api/linked_accounts/github/",
            {"login_enabled": True},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    # ── DELETE ──

    def test_delete_removes_both_identity_and_social_auth(self):
        UserSocialIdentity.objects.create(user=self.user, provider="github", uid="42", extra_data={"login": "octo"})
        UserSocialAuth.objects.create(user=self.user, provider="github", uid="42", extra_data={"login": "octo"})
        response = self.client.delete("/api/linked_accounts/github/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(UserSocialIdentity.objects.filter(user=self.user, provider="github").exists())
        self.assertFalse(UserSocialAuth.objects.filter(user=self.user, provider="github").exists())
        github_row = next(r for r in response.json()["results"] if r["provider"] == "github")
        self.assertFalse(github_row["connected"])

    def test_delete_removes_identity_only_connection(self):
        UserSocialIdentity.objects.create(user=self.user, provider="github", uid="42", extra_data={"login": "octo"})
        response = self.client.delete("/api/linked_accounts/github/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(UserSocialIdentity.objects.filter(user=self.user, provider="github").exists())

    def test_delete_removes_backward_compat_social_auth_only(self):
        UserSocialAuth.objects.create(user=self.user, provider="github", uid="42", extra_data={"login": "octo"})
        response = self.client.delete("/api/linked_accounts/github/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(UserSocialAuth.objects.filter(user=self.user, provider="github").exists())

    def test_delete_rejected_for_enforced_sso_provider(self):
        self._enforce_sso("google-oauth2")
        UserSocialAuth.objects.create(
            user=self.user, provider="google-oauth2", uid="42", extra_data={"email": self.user.email}
        )
        response = self.client.delete("/api/linked_accounts/google-oauth2/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_delete_blocks_when_password_unusable_and_no_alt_login(self):
        self.user.set_unusable_password()
        self.user.save()
        self.client.force_login(self.user)
        UserSocialAuth.objects.create(
            user=self.user, provider="google-oauth2", uid="42", extra_data={"email": self.user.email}
        )
        response = self.client.delete("/api/linked_accounts/google-oauth2/")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertTrue(UserSocialAuth.objects.filter(user=self.user, provider="google-oauth2").exists())

    def test_delete_allowed_when_password_unusable_but_other_login_exists(self):
        self.user.set_unusable_password()
        self.user.save()
        self.client.force_login(self.user)
        UserSocialAuth.objects.create(
            user=self.user, provider="google-oauth2", uid="42", extra_data={"email": self.user.email}
        )
        UserSocialAuth.objects.create(user=self.user, provider="gitlab", uid="9", extra_data={"username": "u"})
        response = self.client.delete("/api/linked_accounts/google-oauth2/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    # ── GitHub link flow ──

    @override_settings(GITHUB_APP_OAUTH_CLIENT_ID="test-client-id", GITHUB_APP_OAUTH_CLIENT_SECRET="test-secret")
    def test_github_start_returns_authorize_url_and_stores_state(self):
        response = self.client.post("/api/linked_accounts/github/start/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertIn("https://github.com/login/oauth/authorize", body["authorize_url"])
        self.assertIn("client_id=test-client-id", body["authorize_url"])

    def test_github_start_without_credentials_returns_400(self):
        with override_settings(GITHUB_APP_OAUTH_CLIENT_ID=""):
            response = self.client.post("/api/linked_accounts/github/start/")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_github_link_creates_identity_only(self):
        cache.set("github_link_state:STATE1", {"user_id": self.user.id}, timeout=60)
        with patch(
            "posthog.api.linked_accounts.GitHubIntegration.github_user_from_code",
            return_value=(99, "octocat"),
        ):
            response = self.client.get("/complete/github-link/?code=abc&state=STATE1")
        self.assertEqual(response.status_code, 302)
        self.assertIn("github_link_success", response["Location"])
        identity = UserSocialIdentity.objects.get(user=self.user, provider="github")
        self.assertEqual(identity.uid, "99")
        self.assertEqual(identity.extra_data["login"], "octocat")
        # No UserSocialAuth created — identity-only.
        self.assertFalse(UserSocialAuth.objects.filter(user=self.user, provider="github").exists())

    def test_github_link_allows_same_uid_linked_to_other_user(self):
        # Multiple PostHog users may hold identity for the same GitHub uid.
        other = User.objects.create_and_join(self.organization, "other@example.com", "x")
        UserSocialIdentity.objects.create(user=other, provider="github", uid="99", extra_data={"login": "octocat"})
        cache.set("github_link_state:STATE1", {"user_id": self.user.id}, timeout=60)
        with patch(
            "posthog.api.linked_accounts.GitHubIntegration.github_user_from_code",
            return_value=(99, "octocat"),
        ):
            response = self.client.get("/complete/github-link/?code=abc&state=STATE1")
        self.assertEqual(response.status_code, 302)
        self.assertIn("github_link_success", response["Location"])
        self.assertTrue(UserSocialIdentity.objects.filter(user=self.user, provider="github", uid="99").exists())
        # Other user's identity is untouched.
        self.assertTrue(UserSocialIdentity.objects.filter(user=other, provider="github", uid="99").exists())

    def test_github_link_preserves_existing_social_auth_for_same_uid(self):
        # Pre-existing login user re-links the same GitHub account. UserSocialAuth stays.
        UserSocialAuth.objects.create(user=self.user, provider="github", uid="99", extra_data={"login": "octocat"})
        cache.set("github_link_state:STATE1", {"user_id": self.user.id}, timeout=60)
        with patch(
            "posthog.api.linked_accounts.GitHubIntegration.github_user_from_code",
            return_value=(99, "octocat"),
        ):
            self.client.get("/complete/github-link/?code=abc&state=STATE1")
        self.assertTrue(UserSocialAuth.objects.filter(user=self.user, provider="github", uid="99").exists())
        self.assertTrue(UserSocialIdentity.objects.filter(user=self.user, provider="github", uid="99").exists())

    def test_github_link_removes_stale_social_auth_for_different_uid(self):
        # If re-linking to a different GitHub account, the old login row is invalidated.
        UserSocialAuth.objects.create(user=self.user, provider="github", uid="11", extra_data={"login": "old"})
        cache.set("github_link_state:STATE1", {"user_id": self.user.id}, timeout=60)
        with patch(
            "posthog.api.linked_accounts.GitHubIntegration.github_user_from_code",
            return_value=(99, "octocat"),
        ):
            self.client.get("/complete/github-link/?code=abc&state=STATE1")
        self.assertFalse(UserSocialAuth.objects.filter(user=self.user, provider="github", uid="11").exists())
        self.assertTrue(UserSocialIdentity.objects.filter(user=self.user, provider="github", uid="99").exists())

    def test_github_link_rejects_mismatched_state(self):
        cache.set("github_link_state:STATE1", {"user_id": self.user.id + 9999}, timeout=60)
        response = self.client.get("/complete/github-link/?code=abc&state=STATE1")
        self.assertEqual(response.status_code, 302)
        self.assertIn("github_link_error", response["Location"])
        self.assertFalse(UserSocialIdentity.objects.filter(user=self.user, provider="github").exists())


class TestGetGithubLoginPrecedence(APIBaseTest):
    """Precedence: UserSocialIdentity > UserSocialAuth > integration."""

    def test_returns_none_when_no_source_present(self):
        self.assertIsNone(self.user.get_github_login())

    def test_uses_identity_when_only_source(self):
        UserSocialIdentity.objects.create(
            user=self.user, provider="github", uid="1", extra_data={"login": "identity-login"}
        )
        self.assertEqual(self.user.get_github_login(), "identity-login")

    def test_uses_social_auth_when_only_source(self):
        UserSocialAuth.objects.create(user=self.user, provider="github", uid="1", extra_data={"login": "auth-login"})
        self.assertEqual(self.user.get_github_login(), "auth-login")

    def test_uses_integration_when_only_source(self):
        from posthog.models.integration import Integration

        Integration.objects.create(
            team=self.team,
            kind="github",
            created_by=self.user,
            config={"connecting_user_github_login": "integration-login"},
        )
        self.assertEqual(self.user.get_github_login(), "integration-login")

    def test_identity_takes_precedence_over_social_auth(self):
        UserSocialIdentity.objects.create(
            user=self.user, provider="github", uid="1", extra_data={"login": "identity-login"}
        )
        UserSocialAuth.objects.create(user=self.user, provider="github", uid="1", extra_data={"login": "auth-login"})
        self.assertEqual(self.user.get_github_login(), "identity-login")

    def test_social_auth_takes_precedence_over_integration(self):
        from posthog.models.integration import Integration

        Integration.objects.create(
            team=self.team,
            kind="github",
            created_by=self.user,
            config={"connecting_user_github_login": "integration-login"},
        )
        UserSocialAuth.objects.create(user=self.user, provider="github", uid="1", extra_data={"login": "auth-login"})
        self.assertEqual(self.user.get_github_login(), "auth-login")


class TestSocialAuthAllowedLoginDisabledGate(APIBaseTest):
    """The login gate rejects when UserSocialIdentity exists but UserSocialAuth doesn't."""

    def test_rejects_when_identity_exists_but_no_social_auth(self):
        UserSocialIdentity.objects.create(user=self.user, provider="github", uid="42", extra_data={"login": "octocat"})
        with self.assertRaises(AuthFailed) as ctx:
            social_auth_allowed(
                backend=type("MockBackend", (), {"name": "github"})(),
                details={"email": self.user.email},
                response={"id": 42},
            )
        self.assertEqual(ctx.exception.args[0], "github_login_disabled_for_account")

    def test_google_error_code_uses_underscore_form(self):
        UserSocialIdentity.objects.create(
            user=self.user, provider="google-oauth2", uid="42", extra_data={"email": self.user.email}
        )
        with self.assertRaises(AuthFailed) as ctx:
            social_auth_allowed(
                backend=type("MockBackend", (), {"name": "google-oauth2"})(),
                details={"email": self.user.email},
                response={"id": 42},
            )
        self.assertEqual(ctx.exception.args[0], "google_login_disabled_for_account")

    def test_allows_when_social_auth_exists(self):
        UserSocialAuth.objects.create(user=self.user, provider="github", uid="42", extra_data={"login": "octocat"})
        # Should not raise.
        social_auth_allowed(
            backend=type("MockBackend", (), {"name": "github"})(),
            details={"email": self.user.email},
            response={"id": 42},
        )

    def test_allows_first_time_login_no_records(self):
        # Neither identity nor social_auth exists → first-time login, allow.
        social_auth_allowed(
            backend=type("MockBackend", (), {"name": "github"})(),
            details={"email": self.user.email},
            response={"id": 999},
        )


class TestGitHubAppInstallIdentityUpsert(APIBaseTest):
    """GitHub App install creates a UserSocialIdentity (identity-only)."""

    def setUp(self):
        super().setUp()
        membership = OrganizationMembership.objects.get(organization=self.organization, user=self.user)
        membership.level = OrganizationMembership.Level.ADMIN
        membership.save()
        self.client.force_login(self.user)
        cache.set(f"github_state:{self.user.id}", "STATE-X", timeout=60)

    def _post_install(self):
        return self.client.post(
            f"/api/environments/{self.team.id}/integrations",
            {
                "kind": "github",
                "config": {"installation_id": "12345", "state": "STATE-X", "code": "abc"},
            },
            content_type="application/json",
        )

    def test_install_creates_identity_not_social_auth(self):
        with (
            patch(
                "posthog.api.integration.GitHubIntegration.integration_from_installation_id",
                return_value=type(
                    "FakeIntegration",
                    (),
                    {"config": {}, "save": lambda self, **_: None, "id": 1, "team_id": self.team.id, "kind": "github"},
                )(),
            ),
            patch(
                "posthog.api.integration.GitHubIntegration.github_user_from_code",
                return_value=(99, "octocat"),
            ),
        ):
            response = self._post_install()
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        identity = UserSocialIdentity.objects.get(user=self.user, provider="github")
        self.assertEqual(identity.uid, "99")
        self.assertEqual(identity.extra_data["login"], "octocat")
        self.assertFalse(UserSocialAuth.objects.filter(user=self.user, provider="github").exists())

    def test_install_allows_identity_when_other_user_has_same_uid(self):
        # Unlike the old model, identity-only linking never collides across users.
        other = User.objects.create_and_join(self.organization, "other2@example.com", "x")
        UserSocialIdentity.objects.create(user=other, provider="github", uid="99", extra_data={"login": "octocat"})
        with (
            patch(
                "posthog.api.integration.GitHubIntegration.integration_from_installation_id",
                return_value=type(
                    "FakeIntegration",
                    (),
                    {"config": {}, "save": lambda self, **_: None, "id": 1, "team_id": self.team.id, "kind": "github"},
                )(),
            ),
            patch(
                "posthog.api.integration.GitHubIntegration.github_user_from_code",
                return_value=(99, "octocat"),
            ),
        ):
            response = self._post_install()
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(UserSocialIdentity.objects.filter(user=self.user, provider="github", uid="99").exists())
        self.assertTrue(UserSocialIdentity.objects.filter(user=other, provider="github", uid="99").exists())
