from datetime import timedelta

from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import override_settings
from django.utils import timezone

from posthog.models.integration import GitHubInstallationAccess, GitHubIntegration, GitHubUserAuthorization
from posthog.models.oauth import OAuthApplication
from posthog.models.user import OnboardingSkippedReason, User

from ee.api.agentic_provisioning import GITHUB_GRANT_CACHE_PREFIX, github_grants
from ee.api.agentic_provisioning.test.base import HMAC_SECRET, ProvisioningTestBase

INSTALLATION_ID = "777"
CODE_CHALLENGE = "a" * 43

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


@override_settings(WIZARD_CLOUD_RUN_OAUTH_CLIENT_ID="wizard-client-id")
class TestAccountRequestsWizardBlock(ProvisioningTestBase):
    def setUp(self):
        super().setUp()
        self.partner = OAuthApplication.objects.create(
            name="Drop Partner",
            client_id="drop_partner_client_id",
            client_secret="",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://posthog.com/api/wizard/oauth-callback",
            algorithm="RS256",
            provisioning_auth_method="hmac",
            provisioning_signing_secret=HMAC_SECRET,
            provisioning_partner_type="posthog_website",
            provisioning_active=True,
            provisioning_can_create_accounts=True,
        )

    def _payload(self, email: str, wizard: dict | None = None) -> dict:
        configuration: dict = {"region": "US"}
        if wizard is not None:
            configuration["wizard"] = wizard
        return {
            "id": "acctreq_wizard123",
            "email": email,
            "code_challenge": CODE_CHALLENGE,
            "configuration": configuration,
        }

    def _grant(self, email: str) -> github_grants.GitHubGrant:
        return github_grants.create_grant(self.partner, AUTHORIZATION, email)

    def _post(self, payload: dict):
        return self._post_signed("/api/agentic/provisioning/account_requests", data=payload)

    def test_without_wizard_block_response_and_email_unchanged(self):
        with patch("ee.api.agentic_provisioning.views.send_provisioning_welcome") as mock_email:
            response = self._post(self._payload("plain@example.com"))
        assert response.status_code == 200, response.json()
        body = response.json()
        assert body["type"] == "oauth"
        assert "wizard" not in body
        assert mock_email.delay.call_count == 1
        args, kwargs = mock_email.delay.call_args
        assert len(args) == 3
        assert kwargs == {}

    def test_bundled_happy_path_runs_wizard_then_emails(self):
        grant = self._grant("drop@example.com")
        created = MagicMock(task_id="task-uuid", latest_run=MagicMock(id="run-uuid", status="queued"))
        manager = MagicMock()
        with (
            patch.object(GitHubIntegration, "verify_user_installation_access", return_value=True),
            patch.object(GitHubIntegration, "fetch_installation_access", return_value=_installation_access()),
            patch.object(GitHubIntegration, "first_for_team_repository", return_value=MagicMock()),
            patch(
                "ee.api.agentic_provisioning.views.tasks_facade.create_wizard_cloud_run", return_value=created
            ) as mock_create,
            patch("ee.api.agentic_provisioning.views.send_provisioning_welcome") as mock_email,
        ):
            manager.attach_mock(mock_create, "create_run")
            manager.attach_mock(mock_email.delay, "email_delay")
            response = self._post(
                self._payload(
                    "drop@example.com",
                    wizard={
                        "grant_id": grant.grant_id,
                        "installation_id": INSTALLATION_ID,
                        "repository": "octocat/hello-world",
                        "branch": "main",
                    },
                )
            )

        assert response.status_code == 200, response.json()
        body = response.json()
        assert body["type"] == "oauth"
        assert body["wizard"] == {"task_id": "task-uuid", "run_id": "run-uuid", "status": "queued"}

        user = User.objects.get(email="drop@example.com")
        team = user.teams.get()
        mock_create.assert_called_once_with(team=team, user_id=user.id, repository="octocat/hello-world", branch="main")

        assert cache.get(f"{GITHUB_GRANT_CACHE_PREFIX}{grant.grant_id}") is None
        assert user.onboarding_skipped_reason == OnboardingSkippedReason.PROVISIONED
        team.refresh_from_db()
        assert team.completed_snippet_onboarding is True

        assert mock_email.delay.call_args.kwargs == {"repository": "octocat/hello-world"}
        call_names = [name for name, _args, _kwargs in manager.mock_calls]
        assert call_names.index("create_run") < call_names.index("email_delay")

    def test_wizard_grant_not_found_returns_account_with_wizard_error(self):
        with patch("ee.api.agentic_provisioning.views.send_provisioning_welcome") as mock_email:
            response = self._post(
                self._payload(
                    "droperr@example.com",
                    wizard={
                        "grant_id": "nonexistent",
                        "installation_id": INSTALLATION_ID,
                        "repository": "octocat/hello-world",
                    },
                )
            )
        assert response.status_code == 200, response.json()
        body = response.json()
        assert body["type"] == "oauth"
        assert "code" in body["oauth"]
        assert body["wizard"]["error"]["code"] == "grant_not_found"
        assert User.objects.filter(email="droperr@example.com").exists()
        assert mock_email.delay.call_args.kwargs == {}

    def test_wizard_ownership_denied_preserves_grant(self):
        grant = self._grant("denied@example.com")
        with (
            patch.object(GitHubIntegration, "verify_user_installation_access", return_value=False),
            patch("ee.api.agentic_provisioning.views.send_provisioning_welcome"),
        ):
            response = self._post(
                self._payload(
                    "denied@example.com",
                    wizard={
                        "grant_id": grant.grant_id,
                        "installation_id": INSTALLATION_ID,
                        "repository": "octocat/hello-world",
                    },
                )
            )
        assert response.status_code == 200
        assert response.json()["wizard"]["error"]["code"] == "installation_access_denied"
        assert cache.get(f"{GITHUB_GRANT_CACHE_PREFIX}{grant.grant_id}") is not None

    @override_settings(WIZARD_CLOUD_RUN_OAUTH_CLIENT_ID="")
    def test_wizard_unavailable_when_cloud_run_not_configured(self):
        grant = self._grant("unavail@example.com")
        with (
            patch.object(GitHubIntegration, "verify_user_installation_access", return_value=True),
            patch.object(GitHubIntegration, "fetch_installation_access", return_value=_installation_access()),
            patch("ee.api.agentic_provisioning.views.send_provisioning_welcome") as mock_email,
        ):
            response = self._post(
                self._payload(
                    "unavail@example.com",
                    wizard={
                        "grant_id": grant.grant_id,
                        "installation_id": INSTALLATION_ID,
                        "repository": "octocat/hello-world",
                    },
                )
            )
        assert response.status_code == 200
        assert response.json()["wizard"]["error"]["code"] == "wizard_unavailable"
        assert mock_email.delay.call_args.kwargs == {}

    def test_existing_user_with_wizard_block_gets_requires_auth_and_grant_survives(self):
        User.objects.create_user(email="existing@example.com", password="hunter2!!", first_name="Ex")
        grant = self._grant("existing@example.com")
        response = self._post(
            self._payload(
                "existing@example.com",
                wizard={
                    "grant_id": grant.grant_id,
                    "installation_id": INSTALLATION_ID,
                    "repository": "octocat/hello-world",
                },
            )
        )
        assert response.status_code == 200, response.json()
        body = response.json()
        assert body["type"] == "requires_auth"
        assert "wizard" not in body
        assert cache.get(f"{GITHUB_GRANT_CACHE_PREFIX}{grant.grant_id}") is not None
