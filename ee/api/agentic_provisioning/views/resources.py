"""Resource endpoints — bearer-authenticated, status envelope.

A "resource" is a provisioned team, addressed by the partner as an opaque
resource id. All endpoints proxy cross-region on bearer lookup and read the
authenticated token off ``request.auth``.
"""

from __future__ import annotations

from typing import cast

from rest_framework.request import Request
from rest_framework.response import Response

from posthog.exceptions_capture import capture_exception
from posthog.models.oauth import OAuthAccessToken
from posthog.models.team.team import Team
from posthog.models.team.team_provisioning_config import TeamProvisioningConfig
from posthog.models.user import User

from ee.api.agentic_provisioning.analytics import capture_provisioning_event
from ee.api.agentic_provisioning.credentials import maybe_create_provisioned_pat
from ee.api.agentic_provisioning.exceptions import ProvisioningError
from ee.api.agentic_provisioning.ratelimits import Budget, rate_limited
from ee.api.agentic_provisioning.regions import current_region_host
from ee.api.agentic_provisioning.serializers import (
    GitHubIntegrationSerializer,
    ResourceCreateSerializer,
    RotateCredentialsSerializer,
    WizardRunSerializer,
)
from ee.api.agentic_provisioning.teams import ProjectIdCollisionError, resolve_or_create_project_team
from ee.api.agentic_provisioning.tokens import remove_team_from_token_scopes
from ee.api.agentic_provisioning.views.base import BearerResourceAPIView
from ee.api.agentic_provisioning.wizard import create_wizard_run, link_github_grant_to_team


def _access_configuration_response(
    *,
    resource_id: str,
    team: Team,
    user: User,
    access_token: OAuthAccessToken,
    label_prefix: str | None,
    mint_pat: bool = True,
) -> Response:
    access_configuration: dict[str, str] = {
        "api_key": team.api_token,
        "host": current_region_host(),
    }
    if mint_pat and (
        personal_api_key := maybe_create_provisioned_pat(
            user, team, access_token.application, access_token.scope, label_prefix=label_prefix
        )
    ):
        access_configuration["personal_api_key"] = personal_api_key

    return Response(
        {
            "status": "complete",
            "id": resource_id,
            "complete": {
                "access_configuration": access_configuration,
            },
        }
    )


class ResourcesCreateView(BearerResourceAPIView):
    @rate_limited("resource_creates", budget=Budget(burst=10, per_hour=30))
    def post(self, request: Request) -> Response:
        user = cast(User, request.user)
        access_token = cast(OAuthAccessToken, request.auth)

        app = access_token.application

        data = self.validated_body(ResourceCreateSerializer, request, context={"partner": app})
        label_prefix = data["label_prefix"]

        scoped_teams = access_token.scoped_teams or []

        if not scoped_teams:
            capture_provisioning_event("resource_created", "error", partner=app, error_code="no_team")
            raise ProvisioningError("no_team", "No team associated with this token")

        project_id = data["project_id"]
        configuration = data["configuration"]

        if project_id:
            try:
                team, scoped_teams = resolve_or_create_project_team(
                    project_id, scoped_teams, user, configuration, access_token
                )
            except ProjectIdCollisionError:
                capture_provisioning_event(
                    "resource_created", "error", partner=app, error_code="project_id_conflict", project_id=project_id
                )
                raise ProvisioningError(
                    "project_id_conflict",
                    "Project ID already linked to another organization",
                    status=409,
                )
            if team is None:
                capture_provisioning_event(
                    "resource_created", "error", partner=app, error_code="not_found", project_id=project_id
                )
                raise ProvisioningError("not_found", "Resource not found", status=404)
        else:
            team_id = scoped_teams[0]
            try:
                team = Team.objects.get(id=team_id)
            except Team.DoesNotExist:
                capture_provisioning_event(
                    "resource_created", "error", partner=app, error_code="team_not_found", team_id=team_id
                )
                raise ProvisioningError("team_not_found", "Team not found", resource_id=str(team_id), status=404)

        capture_provisioning_event(
            "resource_created",
            "success",
            partner=app,
            team_id=team.id,
        )

        return _access_configuration_response(
            resource_id=str(team.id),
            team=team,
            user=user,
            access_token=access_token,
            label_prefix=label_prefix,
        )


class ResourceDetailView(BearerResourceAPIView):
    @rate_limited("resource_reads")
    def get(self, request: Request, resource_id: str) -> Response:
        user = cast(User, request.user)
        access_token = cast(OAuthAccessToken, request.auth)
        team = self.get_scoped_team(resource_id, access_token)

        return _access_configuration_response(
            resource_id=resource_id,
            team=team,
            user=user,
            access_token=access_token,
            label_prefix=None,
            # A read never mints a personal API key; rotation/creation do.
            mint_pat=False,
        )


class RotateCredentialsView(BearerResourceAPIView):
    @rate_limited("credential_rotations")
    def post(self, request: Request, resource_id: str) -> Response:
        user = cast(User, request.user)
        access_token = cast(OAuthAccessToken, request.auth)

        data = self.validated_body(
            RotateCredentialsSerializer, request, resource_id=resource_id, context={"resource_id": resource_id}
        )
        label_prefix = data["label_prefix"]

        team = self.get_scoped_team(resource_id, access_token)

        try:
            # Bearer flow resolves the token outside DRF's session machinery,
            # so read impersonation off the token directly.
            team.reset_token_and_save(user=user, is_impersonated_session=access_token.impersonated_by_id is not None)
        except Exception:
            capture_exception(additional_properties={"team_id": team.id})
            capture_provisioning_event("credential_rotation", "failed", team_id=team.id)
            raise ProvisioningError(
                "credential_rotation_failed", "Failed to rotate credentials", resource_id=resource_id, status=500
            )

        capture_provisioning_event("credential_rotation", "success", team_id=team.id)

        return _access_configuration_response(
            resource_id=resource_id,
            team=team,
            user=user,
            access_token=access_token,
            label_prefix=label_prefix,
        )


class ResourceRemoveView(BearerResourceAPIView):
    """Detaches the resource from the orchestrator: removes it from the token's
    scope and clears provisioning metadata. Preserves the underlying team and
    user data so the customer can still access PostHog directly."""

    @rate_limited("resource_removals")
    def post(self, request: Request, resource_id: str) -> Response:
        access_token = cast(OAuthAccessToken, request.auth)

        team_id = self.parse_resource_team_id(resource_id, access_token)

        try:
            # Clear the mapping only if it is unclaimed or owned by the caller's
            # application; an in-scope partner must not delete another partner's
            # provisioning mapping for the same team.
            config = TeamProvisioningConfig.objects.filter(team_id=team_id).first()
            if config is not None and config.application_id in (None, access_token.application_id):
                config.delete()
        except Exception:
            capture_exception(additional_properties={"team_id": team_id, "step": "remove_provisioning_config"})
            capture_provisioning_event("resource_removed", "error", team_id=team_id, error_code="remove_config_failed")
            raise ProvisioningError("remove_failed", "Failed to remove resource", resource_id=resource_id, status=500)

        remove_team_from_token_scopes(access_token, team_id)

        capture_provisioning_event("resource_removed", "success", team_id=team_id)

        return Response({"status": "removed", "id": resource_id})


class GitHubIntegrationView(BearerResourceAPIView):
    """Link a GitHub installation to the team from a stored grant."""

    @rate_limited("github_integrations")
    def post(self, request: Request, resource_id: str) -> Response:
        user = cast(User, request.user)
        access_token = cast(OAuthAccessToken, request.auth)

        team = self.get_scoped_team(resource_id, access_token)

        data = self.validated_body(
            GitHubIntegrationSerializer, request, resource_id=resource_id, context={"resource_id": resource_id}
        )

        integration, already_linked = link_github_grant_to_team(
            partner=access_token.application,
            user=user,
            team=team,
            grant_id=str(data["grant_id"]),
            installation_id=str(data["installation_id"]),
        )

        return Response(
            {
                "status": "complete",
                "id": resource_id,
                "github_integration": {
                    "integration_id": str(integration.id),
                    "gh_login": (integration.config or {}).get("connecting_user_github_login"),
                    "already_linked": already_linked,
                },
            }
        )


class WizardRunsView(BearerResourceAPIView):
    """Kick off a cloud wizard run against a repository the team's GitHub
    integration can reach.

    Starting a coding-agent run inside a customer's repository reaches a long way past
    provisioning a project, so it needs its own grant rather than following from a partner
    being allowed to provision resources at all. ``create_wizard_run`` enforces that, for
    this endpoint and the account-request wizard block alike.
    """

    # charge="manual": the charge lives inside create_wizard_run, which the bundled
    # account-request wizard block also calls, so retries can't double-spend and the
    # capability check runs before any quota is spent on either path.
    @rate_limited("wizard_runs", charge="manual")
    def post(self, request: Request, resource_id: str) -> Response:
        user = cast(User, request.user)
        access_token = cast(OAuthAccessToken, request.auth)

        team = self.get_scoped_team(resource_id, access_token)

        data = self.validated_body(
            WizardRunSerializer, request, resource_id=resource_id, context={"resource_id": resource_id}
        )

        run_payload = create_wizard_run(
            partner=access_token.application,
            user_id=user.id,
            team=team,
            repository=str(data["repository"]),
            branch=data["branch"],
        )

        return Response({"status": "complete", "id": resource_id, "wizard_run": run_payload})
