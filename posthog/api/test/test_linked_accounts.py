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
from posthog.models.user_social_auth_login_preference import (
    UserSocialAuthLoginPreference,
    available_providers_for_user,
    can_disconnect_provider,
    can_user_enable_login_for,
    default_login_enabled_for,
    effective_login_enabled,
)

from ee.api.authentication import social_auth_allowed


class TestLoginPreferenceHelpers(APIBaseTest):
    def test_default_login_enabled_for_github_is_true_when_no_preference(self):
        # Row absence == sign-in allowed. GitHub identity-only is enforced at write time
        # by the link/install flows creating an explicit opt-out row, not at read time.
        self.assertTrue(default_login_enabled_for(self.user, "github"))

    def test_default_login_enabled_for_google_is_true(self):
        self.assertTrue(default_login_enabled_for(self.user, "google-oauth2"))

    def test_default_login_enabled_with_sso_enforcement_blocks_other_providers(self):
        self._enforce_sso("google-oauth2")
        self.assertFalse(default_login_enabled_for(self.user, "github"))
        self.assertFalse(default_login_enabled_for(self.user, "gitlab"))
        self.assertTrue(default_login_enabled_for(self.user, "google-oauth2"))

    def test_can_user_enable_login_respects_sso_enforcement(self):
        self.assertTrue(can_user_enable_login_for(self.user, "github"))
        self._enforce_sso("google-oauth2")
        self.assertFalse(can_user_enable_login_for(self.user, "github"))
        self.assertTrue(can_user_enable_login_for(self.user, "google-oauth2"))

    def test_effective_login_enabled_grandfathers_existing_rows_without_preference(self):
        # Simulates a pre-feature GH login user: row exists, no preference. Login keeps working.
        sa = UserSocialAuth.objects.create(user=self.user, provider="github", uid="111", extra_data={"login": "j"})
        self.assertTrue(effective_login_enabled(sa))

    def test_effective_login_enabled_uses_preference_opt_out(self):
        sa = UserSocialAuth.objects.create(user=self.user, provider="github", uid="111", extra_data={"login": "j"})
        UserSocialAuthLoginPreference.objects.create(social_auth=sa, login_enabled=False)
        sa = UserSocialAuth.objects.select_related("login_preference").get(pk=sa.pk)
        self.assertFalse(effective_login_enabled(sa))

    def test_default_login_enabled_when_enforced_provider_is_github(self):
        # SSO enforced on github => github login is *on* by default (it's the only sign-in path).
        self._enforce_sso("github")
        self.assertTrue(default_login_enabled_for(self.user, "github"))
        self.assertFalse(default_login_enabled_for(self.user, "google-oauth2"))

    def test_available_providers_narrowed_to_enforced_sso(self):
        with patch(
            "posthog.models.user_social_auth_login_preference.get_instance_available_sso_providers",
            return_value={"google-oauth2": True, "github": True, "gitlab": True},
        ):
            self.assertEqual(set(available_providers_for_user(self.user)), {"google-oauth2", "github", "gitlab"})
            self._enforce_sso("google-oauth2")
            self.assertEqual(available_providers_for_user(self.user), ["google-oauth2"])

    def test_can_disconnect_blocks_enforced_provider(self):
        self._enforce_sso("google-oauth2")
        self.assertFalse(can_disconnect_provider(self.user, "google-oauth2"))
        # Stray non-enforced rows would still be disconnectable if they existed,
        # but in practice the list endpoint hides them under enforcement.
        self.assertTrue(can_disconnect_provider(self.user, "github"))

    def _enforce_sso(self, sso_enforcement: str) -> None:
        # Give the org an SSO license + configure the domain to enforce it.
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
        # Mark the provider as available instance-wide so the enforcement check doesn't short-circuit.
        self._sso_patcher = patch(
            "posthog.models.organization_domain.get_instance_available_sso_providers",
            return_value={"google-oauth2": True, "github": True, "gitlab": True},
        )
        self._sso_patcher.start()
        self.addCleanup(self._sso_patcher.stop)


class TestLinkedAccountsEndpoints(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)
        # By default simulate GitHub + Google configured instance-wide; individual tests
        # override as needed.
        self._providers_patcher = patch(
            "posthog.models.user_social_auth_login_preference.get_instance_available_sso_providers",
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

    def test_list_returns_row_for_each_configured_provider(self):
        response = self.client.get("/api/linked_accounts/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.json()["results"]
        providers = {r["provider"]: r for r in results}
        self.assertEqual(set(providers.keys()), {"google-oauth2", "github"})
        self.assertFalse(providers["google-oauth2"]["connected"])
        self.assertEqual(providers["google-oauth2"]["connect_flow"], "social_login")
        self.assertEqual(providers["google-oauth2"]["connect_path"], "/login/google-oauth2/")
        self.assertFalse(providers["github"]["connected"])
        self.assertEqual(providers["github"]["connect_flow"], "github_link")

    def test_list_marks_connected_row(self):
        # A pre-existing GH UserSocialAuth without a preference row is grandfathered (login enabled).
        UserSocialAuth.objects.create(
            user=self.user, provider="github", uid="42", extra_data={"login": "octo", "id": 42}
        )
        results = self.client.get("/api/linked_accounts/").json()["results"]
        gh = next(r for r in results if r["provider"] == "github")
        self.assertTrue(gh["connected"])
        self.assertEqual(gh["account_identifier"], "octo")
        self.assertTrue(gh["login_enabled"])
        self.assertTrue(gh["can_disconnect"])
        self.assertIsNone(gh["connect_flow"])

    def test_list_reflects_explicit_login_opt_out(self):
        sa = UserSocialAuth.objects.create(user=self.user, provider="github", uid="42", extra_data={"login": "octo"})
        UserSocialAuthLoginPreference.objects.create(social_auth=sa, login_enabled=False)
        results = self.client.get("/api/linked_accounts/").json()["results"]
        gh = next(r for r in results if r["provider"] == "github")
        self.assertFalse(gh["login_enabled"])

    def test_list_only_shows_enforced_provider_when_sso_enforced(self):
        self._enforce_sso("google-oauth2")
        body = self.client.get("/api/linked_accounts/").json()
        self.assertEqual([r["provider"] for r in body["results"]], ["google-oauth2"])
        # And surfaces enforcement state so the frontend can render an info banner.
        self.assertEqual(body["sso_enforcement"], "google-oauth2")
        self.assertEqual(body["sso_enforcement_provider_name"], "Google")

    def test_list_reports_no_enforcement_when_unenforced(self):
        body = self.client.get("/api/linked_accounts/").json()
        self.assertIsNone(body["sso_enforcement"])
        self.assertIsNone(body["sso_enforcement_provider_name"])

    def test_list_surfaces_stray_historical_rows_when_not_sso_enforced(self):
        UserSocialAuth.objects.create(user=self.user, provider="gitlab", uid="42", extra_data={"username": "u"})
        providers = {r["provider"]: r for r in self.client.get("/api/linked_accounts/").json()["results"]}
        self.assertIn("gitlab", providers)
        self.assertTrue(providers["gitlab"]["connected"])

    def test_patch_sets_login_preference(self):
        UserSocialAuth.objects.create(user=self.user, provider="github", uid="42", extra_data={"login": "octo"})
        response = self.client.patch(
            "/api/linked_accounts/github/",
            {"login_enabled": True},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.json()["login_enabled"])
        self.assertTrue(UserSocialAuthLoginPreference.objects.filter(social_auth__user=self.user).exists())

    def test_patch_rejects_enable_when_sso_enforcement_blocks(self):
        self._enforce_sso("google-oauth2")
        UserSocialAuth.objects.create(user=self.user, provider="github", uid="42", extra_data={"login": "octo"})
        response = self.client.patch(
            "/api/linked_accounts/github/",
            {"login_enabled": True},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_delete_rejected_for_enforced_sso_provider(self):
        self._enforce_sso("google-oauth2")
        UserSocialAuth.objects.create(
            user=self.user, provider="google-oauth2", uid="42", extra_data={"email": self.user.email}
        )
        response = self.client.delete("/api/linked_accounts/google-oauth2/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue(UserSocialAuth.objects.filter(user=self.user, provider="google-oauth2").exists())

    def test_delete_returns_refreshed_list_and_removes_row(self):
        UserSocialAuth.objects.create(user=self.user, provider="github", uid="42", extra_data={"login": "octo"})
        response = self.client.delete("/api/linked_accounts/github/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(UserSocialAuth.objects.filter(user=self.user, provider="github").exists())
        # Endpoint returns the refreshed list so the client doesn't have to GET separately.
        body = response.json()
        github_row = next(r for r in body["results"] if r["provider"] == "github")
        self.assertFalse(github_row["connected"])

    def test_delete_blocks_when_password_unusable_and_no_alt_login(self):
        # Without a usable password and no other login-enabled provider, disconnecting the
        # only sign-in path must fail — exercises the guardrail branch directly.
        self.user.set_unusable_password()
        self.user.save()
        self.client.force_login(self.user)
        sa = UserSocialAuth.objects.create(
            user=self.user, provider="google-oauth2", uid="42", extra_data={"email": self.user.email}
        )
        self.assertTrue(effective_login_enabled(sa))
        response = self.client.delete("/api/linked_accounts/google-oauth2/")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertTrue(UserSocialAuth.objects.filter(user=self.user, provider="google-oauth2").exists())

    def test_delete_allowed_when_password_unusable_but_other_login_provider_exists(self):
        # Same setup but with a second login-enabled provider — guardrail should let it through.
        self.user.set_unusable_password()
        self.user.save()
        self.client.force_login(self.user)
        UserSocialAuth.objects.create(
            user=self.user, provider="google-oauth2", uid="42", extra_data={"email": self.user.email}
        )
        UserSocialAuth.objects.create(user=self.user, provider="gitlab", uid="9", extra_data={"username": "u"})
        response = self.client.delete("/api/linked_accounts/google-oauth2/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(UserSocialAuth.objects.filter(user=self.user, provider="google-oauth2").exists())

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

    def test_github_link_complete_creates_social_auth_with_login_opt_out(self):
        cache.set("github_link_state:STATE1", {"user_id": self.user.id}, timeout=60)
        with patch(
            "posthog.api.linked_accounts.GitHubIntegration.github_user_from_code",
            return_value=(99, "octocat"),
        ):
            response = self.client.get("/complete/github-link/?code=abc&state=STATE1")

        self.assertEqual(response.status_code, 302)
        self.assertIn("github_link_success", response["Location"])
        sa = UserSocialAuth.objects.select_related("login_preference").get(user=self.user, provider="github")
        self.assertEqual(sa.uid, "99")
        self.assertEqual(sa.extra_data["login"], "octocat")
        # Identity-only by default — link flow stamps an explicit opt-out row.
        self.assertFalse(sa.login_preference.login_enabled)

    def test_github_link_complete_does_not_clobber_existing_login_preference(self):
        # Pre-existing GH login user (no preference row → grandfathered as login-enabled).
        UserSocialAuth.objects.create(user=self.user, provider="github", uid="99", extra_data={"login": "octocat"})
        cache.set("github_link_state:STATE1", {"user_id": self.user.id}, timeout=60)
        with patch(
            "posthog.api.linked_accounts.GitHubIntegration.github_user_from_code",
            return_value=(99, "octocat"),
        ):
            self.client.get("/complete/github-link/?code=abc&state=STATE1")
        # No preference row was created — the row already existed, so the user keeps signing in.
        self.assertFalse(UserSocialAuthLoginPreference.objects.filter(social_auth__user=self.user).exists())

    def test_github_link_complete_rejects_mismatched_state(self):
        cache.set("github_link_state:STATE1", {"user_id": self.user.id + 9999}, timeout=60)
        response = self.client.get("/complete/github-link/?code=abc&state=STATE1")
        self.assertEqual(response.status_code, 302)
        self.assertIn("github_link_error", response["Location"])
        self.assertFalse(UserSocialAuth.objects.filter(user=self.user, provider="github").exists())

    def test_github_link_complete_blocks_account_already_linked_to_other_user(self):
        other = User.objects.create_and_join(self.organization, "other@example.com", "x")
        UserSocialAuth.objects.create(user=other, provider="github", uid="99", extra_data={"login": "octocat"})
        cache.set("github_link_state:STATE1", {"user_id": self.user.id}, timeout=60)
        with patch(
            "posthog.api.linked_accounts.GitHubIntegration.github_user_from_code",
            return_value=(99, "octocat"),
        ):
            response = self.client.get("/complete/github-link/?code=abc&state=STATE1")
        self.assertEqual(response.status_code, 302)
        self.assertIn("already_linked", response["Location"])
        self.assertFalse(UserSocialAuth.objects.filter(user=self.user, provider="github").exists())

    def test_list_does_not_offer_connect_for_saml(self):
        # SAML linking can't be initiated from a button — would 400 without an email param.
        # The frontend should see connect_flow=null and render a non-actionable state.
        with patch(
            "posthog.models.user_social_auth_login_preference.get_instance_available_sso_providers",
            return_value={"google-oauth2": False, "github": False, "gitlab": False, "saml": True},
        ):
            self._enforce_sso("saml")
            results = self.client.get("/api/linked_accounts/").json()["results"]
            saml = next(r for r in results if r["provider"] == "saml")
            self.assertIsNone(saml["connect_flow"])
            self.assertIsNone(saml["connect_path"])


class TestGetGithubLoginPrecedence(APIBaseTest):
    """``User.get_github_login`` should prefer the auth-side record over the integration's
    ``connecting_user_github_login``. Auth (OAuth App) is the authoritative identity signal;
    the integration's stored login is a fallback for the rare case a user linked only via App
    install (different GitHub App entirely).
    """

    def test_returns_none_when_no_source_present(self):
        self.assertIsNone(self.user.get_github_login())

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
    """Direct unit tests for the new login-disabled gate in `social_auth_allowed`."""

    def test_social_auth_allowed_rejects_when_preference_opts_out_of_login(self):
        sa = UserSocialAuth.objects.create(user=self.user, provider="github", uid="42", extra_data={"login": "octocat"})
        UserSocialAuthLoginPreference.objects.create(social_auth=sa, login_enabled=False)

        with self.assertRaises(AuthFailed) as ctx:
            social_auth_allowed(
                backend=type("MockBackend", (), {"name": "github"})(),
                details={"email": self.user.email},
                response={"id": 42},
            )
        self.assertEqual(ctx.exception.args[0], "github_login_disabled_for_account")

    def test_social_auth_allowed_google_error_code_uses_underscore_form(self):
        # backend.name is `google-oauth2` (hyphen); the emitted code must use an underscore
        # form so the frontend ERROR_MESSAGES dict can map it cleanly.
        sa = UserSocialAuth.objects.create(
            user=self.user, provider="google-oauth2", uid="42", extra_data={"email": self.user.email}
        )
        UserSocialAuthLoginPreference.objects.create(social_auth=sa, login_enabled=False)

        with self.assertRaises(AuthFailed) as ctx:
            social_auth_allowed(
                backend=type("MockBackend", (), {"name": "google-oauth2"})(),
                details={"email": self.user.email},
                response={"id": 42},
            )
        self.assertEqual(ctx.exception.args[0], "google_login_disabled_for_account")

    def test_social_auth_allowed_passes_through_when_no_preference_row(self):
        # Pre-feature row, no preference row → grandfathered as login-enabled.
        UserSocialAuth.objects.create(user=self.user, provider="github", uid="42", extra_data={"login": "octocat"})

        # Should not raise.
        social_auth_allowed(
            backend=type("MockBackend", (), {"name": "github"})(),
            details={"email": self.user.email},
            response={"id": 42},
        )


class TestGitHubAppInstallIdentityUpsert(APIBaseTest):
    """The GitHub App install path should opt-in newly linked users to identity-only."""

    def setUp(self):
        super().setUp()
        # Integration creation requires admin-level project membership.
        membership = OrganizationMembership.objects.get(organization=self.organization, user=self.user)
        membership.level = OrganizationMembership.Level.ADMIN
        membership.save()
        self.client.force_login(self.user)
        cache.set(f"github_state:{self.user.id}", "STATE-X", timeout=60)

    def _post_install(self):
        # The integration endpoint requires both the installation_id and a state token in the body.
        return self.client.post(
            f"/api/environments/{self.team.id}/integrations",
            {
                "kind": "github",
                "config": {"installation_id": "12345", "state": "STATE-X", "code": "abc"},
            },
            content_type="application/json",
        )

    def test_install_upserts_user_social_auth_with_login_opt_out(self):
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
        sa = UserSocialAuth.objects.select_related("login_preference").get(user=self.user, provider="github")
        self.assertEqual(sa.uid, "99")
        self.assertFalse(sa.login_preference.login_enabled)

    def test_install_silently_skips_identity_upsert_on_collision(self):
        # The integration-App and auth-OAuth-App are different GitHub Apps, so the implicit
        # identity link is best-effort. If the GH user is already mapped to a different PostHog
        # user, we simply skip — the integration install still succeeds.
        other = User.objects.create_and_join(self.organization, "other2@example.com", "x")
        UserSocialAuth.objects.create(user=other, provider="github", uid="99", extra_data={"login": "octocat"})

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
        # No identity row created for the installing user — the other user keeps theirs.
        self.assertFalse(UserSocialAuth.objects.filter(user=self.user, provider="github").exists())
        self.assertTrue(UserSocialAuth.objects.filter(user=other, provider="github").exists())
