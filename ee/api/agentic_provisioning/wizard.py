"""Drop-flow actions: linking a stored GitHub grant to a team and starting
cloud wizard runs against a repository."""

from __future__ import annotations

from django.conf import settings
from django.utils import timezone

from rest_framework.exceptions import ValidationError as DRFValidationError

from posthog.api.github_callback.team_services import link_github_installation_for_user
from posthog.exceptions_capture import capture_exception
from posthog.models.integration import GitHubInstallationAccessFetchError, GitHubIntegration, Integration
from posthog.models.oauth import OAuthApplication
from posthog.models.team.team import Team
from posthog.models.user import OnboardingSkippedReason, User

from products.tasks.backend.facade import api as tasks_facade

from ee.api.agentic_provisioning import github_grants
from ee.api.agentic_provisioning.analytics import capture_provisioning_event
from ee.api.agentic_provisioning.exceptions import ProvisioningError
from ee.api.agentic_provisioning.throttling import enforce_partner_rate_limit, enforce_wizard_run_user_rate_limit


def _drf_validation_error_code(exc: DRFValidationError) -> str | None:
    codes = exc.get_codes()
    if isinstance(codes, list) and codes:
        return str(codes[0])
    if isinstance(codes, str):
        return codes
    return None


def apply_provisioned_onboarding_flags(user: User, team: Team) -> None:
    """Keep the app from routing a partner-provisioned account into onboarding on first
    login. Only applied to unclaimed accounts (never logged in, no password set) so an
    existing user going through the consent path keeps their onboarding state."""
    # Bootstrapped accounts store password="" (create_user skips set_password when the
    # password is None), which Django counts as *usable* — treat it as no password.
    has_password = bool(user.password) and user.has_usable_password()
    if user.last_login is not None or has_password:
        return
    if user.onboarding_skipped_at is None:
        user.onboarding_skipped_at = timezone.now()
    user.onboarding_skipped_reason = OnboardingSkippedReason.PROVISIONED
    user.onboarding_skipped_organization_id = team.organization_id
    user.save(
        update_fields=["onboarding_skipped_at", "onboarding_skipped_reason", "onboarding_skipped_organization_id"]
    )
    if not team.completed_snippet_onboarding:
        team.completed_snippet_onboarding = True
        team.save(update_fields=["completed_snippet_onboarding"])


def link_github_grant_to_team(
    *, partner: OAuthApplication, user: User, team: Team, grant_id: str, installation_id: str
) -> tuple[Integration, bool]:
    """Shared core of the github_integration action and the account_requests wizard
    block: validate the grant, verify installation ownership, create both GitHub
    records, consume the grant. Returns (integration, already_linked); raises
    :class:`ProvisioningError` on failure.
    """
    grant = github_grants.load_grant(grant_id, partner)
    if grant is None:
        # Idempotent retry: the grant is consumed on success, so a retry after a lost
        # response must not fail if the installation is already linked to this team.
        existing = Integration.objects.first_github_for_team_installation(team.id, str(installation_id))
        if existing is not None:
            return existing, True
        capture_provisioning_event("github_integration", "error", partner=partner, error_code="grant_not_found")
        raise ProvisioningError("grant_not_found", "Grant not found or expired", resource_id=str(team.id), status=404)

    try:
        integration = link_github_installation_for_user(
            user=user, team_id=team.id, installation_id=str(installation_id), authorization=grant.to_authorization()
        )
    except DRFValidationError as exc:
        code = _drf_validation_error_code(exc)
        if code == "installation_access_denied":
            capture_provisioning_event("github_integration", "error", partner=partner, error_code=code)
            raise ProvisioningError(
                "installation_access_denied",
                "The GitHub user does not have access to this installation",
                resource_id=str(team.id),
                status=403,
            )
        if code == "installation_verify_failed":
            capture_provisioning_event("github_integration", "error", partner=partner, error_code=code)
            raise ProvisioningError(
                "installation_verify_failed",
                "Could not verify installation access with GitHub",
                resource_id=str(team.id),
                status=502,
            )
        capture_provisioning_event("github_integration", "error", partner=partner, error_code="invalid_request")
        raise ProvisioningError("invalid_request", str(exc.detail), resource_id=str(team.id), status=400)
    except GitHubInstallationAccessFetchError:
        capture_provisioning_event(
            "github_integration", "error", partner=partner, error_code="integration_creation_failed"
        )
        raise ProvisioningError(
            "integration_creation_failed",
            "Could not create the GitHub integration",
            resource_id=str(team.id),
            status=502,
        )

    github_grants.consume_grant(grant_id)
    capture_provisioning_event("github_integration", "success", partner=partner, team_id=team.id)
    return integration, False


def _github_integration_required_error(partner: OAuthApplication, team: Team) -> ProvisioningError:
    capture_provisioning_event(
        "wizard_run", "error", partner=partner, error_code="github_integration_required", team_id=team.id
    )
    return ProvisioningError(
        "github_integration_required",
        "The team does not have a GitHub integration that can access this repository",
        resource_id=str(team.id),
        status=400,
    )


def create_wizard_run(
    *, partner: OAuthApplication, user_id: int, team: Team, repository: str, branch: str | None
) -> dict[str, str]:
    """Gate + throttle + create a cloud wizard run. Returns the run payload;
    raises :class:`ProvisioningError` on failure."""
    # Checked here rather than in each caller: the resource endpoint and the account-request
    # wizard block both land on this function, so this is the one place a new caller cannot
    # forget. Before the rate limits, so a partner without the grant can't spend its quota.
    if not partner.provisioning.can_start_wizard_runs:
        capture_provisioning_event("wizard_run", "error", partner=partner, error_code="forbidden")
        raise ProvisioningError(
            "forbidden",
            "Starting wizard runs is not enabled for this partner",
            resource_id=str(team.id),
            status=403,
        )

    if not bool(settings.WIZARD_CLOUD_RUN_OAUTH_CLIENT_ID):
        capture_provisioning_event("wizard_run", "error", partner=partner, error_code="wizard_unavailable")
        raise ProvisioningError(
            "wizard_unavailable",
            "Running the setup wizard in the cloud is not available",
            resource_id=str(team.id),
            status=503,
        )

    repository = (repository or "").strip()
    parts = repository.split("/")
    if len(parts) != 2 or not all(parts):
        raise ProvisioningError(
            "invalid_request", "repository must be in 'owner/repo' format", resource_id=str(team.id)
        )

    enforce_wizard_run_user_rate_limit(user_id, resource_id=str(team.id))
    enforce_partner_rate_limit(partner, "wizard_runs")

    # Verifying the grant user owns the installation doesn't prove the installation can
    # reach the requested repo — a valid grant for one installation could otherwise report
    # wizard success for an owner/repo it can't operate on. Fail fast instead (after the
    # rate limits, so this GitHub call can't be used as an unthrottled probe).
    if GitHubIntegration.first_for_team_repository(team.id, repository, source="integration") is None:
        raise _github_integration_required_error(partner, team)

    try:
        created = tasks_facade.create_wizard_cloud_run(
            team=team, user_id=user_id, repository=repository, branch=branch or None
        )
    except ValueError:
        # The facade raises when the team has no usable GitHub integration.
        raise _github_integration_required_error(partner, team)
    except Exception:
        capture_exception(additional_properties={"team_id": team.id, "step": "provisioning_wizard_run"})
        capture_provisioning_event(
            "wizard_run", "error", partner=partner, error_code="run_creation_failed", team_id=team.id
        )
        raise ProvisioningError(
            "run_creation_failed", "Failed to start the wizard run", resource_id=str(team.id), status=500
        )

    run = created.latest_run
    capture_provisioning_event("wizard_run", "success", partner=partner, team_id=team.id, task_id=str(created.task_id))
    return {
        "task_id": str(created.task_id),
        "run_id": str(run.id) if run else "",
        "status": str(run.status) if run else "queued",
    }
