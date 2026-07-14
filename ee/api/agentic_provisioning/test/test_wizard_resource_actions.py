from datetime import timedelta

from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import override_settings
from django.utils import timezone

import requests
from parameterized import parameterized

from posthog.models.integration import GitHubInstallationAccess, GitHubIntegration, GitHubUserAuthorization, Integration
from posthog.models.oauth import OAuthApplication
from posthog.models.team.team import Team
from posthog.models.user import OnboardingSkippedReason
from posthog.models.user_integration import UserIntegration

from ee.api.agentic_provisioning import GITHUB_GRANT_CACHE_PREFIX, github_grants
from ee.api.agentic_provisioning.test.base import TEST_STRIPE_OAUTH_CLIENT_ID, ProvisioningTestBase

INSTALLATION_ID = "777"

AUTHORIZATION = GitHubUserAuthorization(
    gh_id=12345,
    gh_login="octocat",
    access_token="gho_secret_user_token",
    refresh_token="ghr_refresh_token",
    access_token_expires_in=28800,
    refresh_token_expires_in=15897600,
)


def _installation_access() -> GitHubInstallationAccess:
    return GitHubInstallationAccess(
        installation_id=INSTALLATION_ID,
        installation_info={"account": {"type": "User", "login": "octocat"}},
        access_token="ghs_installation_token",
        token_expires_at=(timezone.now() + timedelta(hours=1)).isoformat(),
        repository_selection="selected",
    )


class TestWizardResourceActions(ProvisioningTestBase):
    def setUp(self):
        super().setUp()
        self.bearer = self._get_bearer_token()
        self.partner = OAuthApplication.objects.get(client_id=TEST_STRIPE_OAUTH_CLIENT_ID)

    def _grant(self) -> github_grants.GitHubGrant:
        return github_grants.create_grant(self.partner, AUTHORIZATION, "octocat@example.com")

    def _post_github_integration(self, team_id: int, body: dict):
        return self._post_signed_with_bearer(
            f"/api/agentic/provisioning/resources/{team_id}/github_integration", body, token=self.bearer
        )

    def _post_wizard_runs(self, team_id: int, body: dict):
        return self._post_signed_with_bearer(
            f"/api/agentic/provisioning/resources/{team_id}/wizard_runs", body, token=self.bearer
        )

    def _mark_user_unclaimed(self):
        self.user.set_unusable_password()
        self.user.last_login = None
        self.user.save()

    def test_github_integration_happy_path_links_and_consumes_grant(self):
        self._mark_user_unclaimed()
        grant = self._grant()
        with (
            patch.object(GitHubIntegration, "verify_user_installation_access", return_value=True),
            patch.object(GitHubIntegration, "fetch_installation_access", return_value=_installation_access()),
        ):
            response = self._post_github_integration(
                self.team.id, {"grant_id": grant.grant_id, "installation_id": INSTALLATION_ID}
            )

        assert response.status_code == 200, response.json()
        body = response.json()
        assert body["status"] == "complete"
        assert body["github_integration"]["gh_login"] == "octocat"
        assert body["github_integration"]["already_linked"] is False

        integration = Integration.objects.get(team_id=self.team.id, kind="github", integration_id=INSTALLATION_ID)
        assert integration.config["connecting_user_github_login"] == "octocat"
        assert UserIntegration.objects.filter(
            user=self.user, kind=UserIntegration.IntegrationKind.GITHUB, integration_id=INSTALLATION_ID
        ).exists()

        assert cache.get(f"{GITHUB_GRANT_CACHE_PREFIX}{grant.grant_id}") is None

        self.user.refresh_from_db()
        self.team.refresh_from_db()
        assert self.user.onboarding_skipped_reason == OnboardingSkippedReason.PROVISIONED
        assert self.user.onboarding_skipped_at is not None
        assert self.user.onboarding_skipped_organization_id == self.team.organization_id
        assert self.team.completed_snippet_onboarding is True

    def test_github_integration_does_not_touch_onboarding_for_claimed_user(self):
        grant = self._grant()
        with (
            patch.object(GitHubIntegration, "verify_user_installation_access", return_value=True),
            patch.object(GitHubIntegration, "fetch_installation_access", return_value=_installation_access()),
        ):
            response = self._post_github_integration(
                self.team.id, {"grant_id": grant.grant_id, "installation_id": INSTALLATION_ID}
            )
        assert response.status_code == 200
        self.user.refresh_from_db()
        assert self.user.onboarding_skipped_reason is None
        assert self.user.onboarding_skipped_at is None

    def test_github_integration_unknown_grant_returns_404(self):
        response = self._post_github_integration(
            self.team.id, {"grant_id": "nonexistent", "installation_id": INSTALLATION_ID}
        )
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "grant_not_found"

    def test_github_integration_idempotent_retry_after_grant_consumed(self):
        self._mark_user_unclaimed()
        Integration.objects.create(
            team_id=self.team.id,
            kind="github",
            integration_id=INSTALLATION_ID,
            config={"installation_id": INSTALLATION_ID},
            sensitive_config={},
        )
        response = self._post_github_integration(
            self.team.id, {"grant_id": "already-consumed", "installation_id": INSTALLATION_ID}
        )
        assert response.status_code == 200
        assert response.json()["github_integration"]["already_linked"] is True

        # Onboarding flags are re-applied on the already-linked retry so a crash between
        # grant consumption and the flag write doesn't leave the account routed into onboarding.
        self.user.refresh_from_db()
        assert self.user.onboarding_skipped_reason == OnboardingSkippedReason.PROVISIONED
        assert self.user.onboarding_skipped_at is not None

    @parameterized.expand(
        [
            ("access_denied", {"return_value": False}, 403, "installation_access_denied"),
            (
                "verify_error",
                {"side_effect": requests.RequestException("boom")},
                502,
                "installation_verify_failed",
            ),
        ]
    )
    def test_github_integration_ownership_failures_preserve_grant(self, _name, verify_kwargs, status, code):
        grant = self._grant()
        with patch.object(GitHubIntegration, "verify_user_installation_access", **verify_kwargs):
            response = self._post_github_integration(
                self.team.id, {"grant_id": grant.grant_id, "installation_id": INSTALLATION_ID}
            )
        assert response.status_code == status
        assert response.json()["error"]["code"] == code
        assert cache.get(f"{GITHUB_GRANT_CACHE_PREFIX}{grant.grant_id}") is not None

    def test_github_integration_team_outside_token_scope_returns_403(self):
        other_team = Team.objects.create(organization=self.organization, name="other")
        grant = self._grant()
        response = self._post_github_integration(
            other_team.id, {"grant_id": grant.grant_id, "installation_id": INSTALLATION_ID}
        )
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "forbidden"

    @override_settings(WIZARD_CLOUD_RUN_OAUTH_CLIENT_ID="")
    def test_wizard_runs_unavailable_without_oauth_client_id(self):
        response = self._post_wizard_runs(self.team.id, {"repository": "octocat/hello-world"})
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "wizard_unavailable"

    @override_settings(WIZARD_CLOUD_RUN_OAUTH_CLIENT_ID="wizard-client-id")
    def test_wizard_runs_happy_path(self):
        created = MagicMock(task_id="task-uuid", latest_run=MagicMock(id="run-uuid", status="queued"))
        with patch(
            "ee.api.agentic_provisioning.views.tasks_facade.create_wizard_cloud_run", return_value=created
        ) as mock_create:
            response = self._post_wizard_runs(self.team.id, {"repository": "octocat/hello-world", "branch": "main"})

        assert response.status_code == 200, response.json()
        body = response.json()
        assert body["status"] == "complete"
        assert body["wizard_run"] == {"task_id": "task-uuid", "run_id": "run-uuid", "status": "queued"}
        mock_create.assert_called_once_with(
            team=self.team, user_id=self.user.id, repository="octocat/hello-world", branch="main"
        )

    @parameterized.expand(
        [
            ("missing_repository", {}, "invalid_request"),
            ("bad_format", {"repository": "not-a-repo"}, "invalid_request"),
            ("too_many_parts", {"repository": "a/b/c"}, "invalid_request"),
        ]
    )
    @override_settings(WIZARD_CLOUD_RUN_OAUTH_CLIENT_ID="wizard-client-id")
    def test_wizard_runs_rejects_invalid_repository(self, _name, body, code):
        response = self._post_wizard_runs(self.team.id, body)
        assert response.status_code == 400
        assert response.json()["error"]["code"] == code

    @override_settings(WIZARD_CLOUD_RUN_OAUTH_CLIENT_ID="wizard-client-id")
    def test_wizard_runs_per_user_burst_limit(self):
        created = MagicMock(task_id="task-uuid", latest_run=None)
        with patch("ee.api.agentic_provisioning.views.tasks_facade.create_wizard_cloud_run", return_value=created):
            first = self._post_wizard_runs(self.team.id, {"repository": "octocat/one"})
            second = self._post_wizard_runs(self.team.id, {"repository": "octocat/two"})
            third = self._post_wizard_runs(self.team.id, {"repository": "octocat/three"})
        assert first.status_code == 200
        assert second.status_code == 200
        assert third.status_code == 429
        assert third["Retry-After"]

    @override_settings(WIZARD_CLOUD_RUN_OAUTH_CLIENT_ID="wizard-client-id")
    def test_wizard_runs_without_github_integration_returns_400(self):
        with patch(
            "ee.api.agentic_provisioning.views.tasks_facade.create_wizard_cloud_run",
            side_effect=ValueError("Team has no GitHub integration"),
        ):
            response = self._post_wizard_runs(self.team.id, {"repository": "octocat/hello-world"})
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "github_integration_required"
