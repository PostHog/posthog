import os
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast
from urllib.parse import parse_qsl, urlencode, urlparse

from django.core.cache import cache
from django.http import HttpRequest
from django.utils.crypto import get_random_string

import requests
import structlog
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.request import Request

from posthog.api.github_callback import (
    redirects,
    state as github_callback_state,
)
from posthog.api.github_callback.types import (
    FinishResult,
    FlowKind,
    GitHubAuthorizeState,
    github_oauth_authorize_url,
    is_valid_github_installation_id,
)
from posthog.auth import SessionAuthentication
from posthog.models import Team
from posthog.models.integration import (
    GitHubInstallationAccess,
    GitHubInstallationAccessFetchError,
    GitHubIntegration,
    Integration,
    invalidate_github_repository_caches_for_installation,
)
from posthog.models.organization import Organization
from posthog.models.user import User
from posthog.models.user_integration import UserIntegration, user_github_integration_from_installation
from posthog.utils import is_relative_url

logger = structlog.get_logger(__name__)

GITHUB_LINK_EXISTING_ERROR_ORPHAN_INSTALLATION = "github_link_existing_orphan_installation"
GITHUB_LINK_EXISTING_ERROR_PERSONAL_GITHUB_REQUIRED = "github_link_existing_personal_github_required"
PERSONAL_GITHUB_REQUIRED_MESSAGE = (
    "You must connect your personal GitHub account (via Linked Accounts) before linking an existing "
    "installation, to confirm you have access to the GitHub App installation."
)


@dataclass(frozen=True)
class TeamGitHubFinishSetupResult:
    next_url: str
    installation_id: str
    integration: Integration | None = None
    oauth_url: str | None = None


def _validation_error_code(exc: ValidationError) -> str | None:
    codes = exc.get_codes()
    if isinstance(codes, list) and codes:
        return str(codes[0])
    if isinstance(codes, dict) and codes:
        first = next(iter(codes.values()))
        if isinstance(first, list) and first:
            return str(first[0])
        return str(first)
    if isinstance(codes, str):
        return codes
    return None


def _connect_from_for_next(next_url: str) -> str | None:
    connect_from = dict(parse_qsl(urlparse(next_url).query)).get("connect_from")
    return connect_from if connect_from == "posthog_code" else None


def create_team_github_integration_from_oauth_code(
    *,
    request: Request,
    user: User,
    team_id: int,
    installation_id: str | None,
    state_token: str | None,
    code: str | None,
) -> Integration:
    if not installation_id:
        raise ValidationError("An installation_id must be provided")

    if not state_token:
        raise ValidationError("A state token must be provided")

    if not code:
        raise ValidationError("An OAuth code must be provided")

    github_callback_state.consume_github_authorize_state(request, state_token)

    authorization = GitHubIntegration.github_user_from_code(code)
    if authorization is None:
        raise ValidationError("Failed to exchange the OAuth code — ensure GITHUB_APP_CLIENT_SECRET is configured")

    if not is_valid_github_installation_id(installation_id):
        raise ValidationError("Invalid installation_id")
    try:
        has_access = GitHubIntegration.verify_user_installation_access(installation_id, authorization.access_token)
    except requests.RequestException:
        logger.warning(
            "github_integration_create: installation ownership check failed",
            installation_id=installation_id,
            user_id=user.id,
            exc_info=True,
        )
        raise ValidationError("Failed to verify installation access")
    if not has_access:
        logger.warning(
            "github_integration_create: user does not have access to installation",
            installation_id=installation_id,
            user_id=user.id,
        )
        raise ValidationError("You do not have access to this GitHub installation")

    instance = GitHubIntegration.integration_from_installation_id(installation_id, team_id, user)

    instance.config["connecting_user_github_login"] = authorization.gh_login
    instance.save(update_fields=["config"])
    refreshed_at = instance.config.get("refreshed_at", 0)
    expires_in = instance.config.get("expires_in", 3600)
    token_expires_at = datetime.fromtimestamp(refreshed_at + expires_in, tz=UTC).isoformat()
    user_github_integration_from_installation(
        user,
        GitHubInstallationAccess(
            installation_id=installation_id,
            installation_info=instance.config,
            access_token=instance.sensitive_config.get("access_token", ""),
            token_expires_at=token_expires_at,
            repository_selection=instance.config.get("repository_selection", "selected"),
        ),
        authorization,
        create_only=True,
    )

    return instance


def finish_team_github_setup_update(
    *,
    user: User,
    team_id: int,
    request: Request,
    installation_id: str,
    existing: Integration,
    state_raw: str | None,
    fallback_next_url: str | None,
) -> TeamGitHubFinishSetupResult:
    installation_id_str = str(installation_id)
    next_url = fallback_next_url or ""

    if cache.get(github_callback_state.unified_authorize_pending_cache_key(user.id)) is not None:
        _, next_url, _ = github_callback_state.consume_github_authorize_state(
            request, state_raw, setup_action="update", code=None, installation_id=installation_id_str
        )

    refreshed = refresh_team_github_integration(user, team_id, installation_id_str, existing=existing)
    return TeamGitHubFinishSetupResult(
        next_url=next_url or redirects.landing_url(fallback_next_url, team_id),
        installation_id=installation_id_str,
        integration=refreshed,
    )


def execute_team_github_finish_setup(
    *,
    user: User,
    team: Team,
    request: Request,
    installation_id: str,
    code: str | None,
    setup_action: str,
    state_raw: str | None,
) -> TeamGitHubFinishSetupResult:
    if not is_valid_github_installation_id(installation_id):
        raise ValidationError("Invalid installation_id")

    installation_id_str = str(installation_id)

    _state_token, next_url, _team_id = github_callback_state.consume_github_authorize_state(
        request, state_raw, setup_action=setup_action, code=code, installation_id=installation_id_str
    )

    is_already_installed = setup_action == "update" or not code
    connect_from = _connect_from_for_next(next_url)

    if is_already_installed:
        try:
            organization = team.organization
            existing_install = (
                Integration.objects.filter(
                    team__organization_id=organization.id,
                    kind="github",
                )
                .for_github_installation_id(installation_id_str)
                .order_by("id")
                .first()
            )
            if existing_install is None:
                raise ValidationError(
                    "No team in your organization has this GitHub installation linked",
                    code=GITHUB_LINK_EXISTING_ERROR_ORPHAN_INSTALLATION,
                )

            source_installation_id = (existing_install.config or {}).get("installation_id")
            if not source_installation_id:
                raise ValidationError("Source integration is missing installation_id")

            user_github_integration = (
                UserIntegration.objects.filter(user=user, kind="github").order_by("-created_at").first()
            )
            user_access_token = (
                user_github_integration.sensitive_config.get("access_token") if user_github_integration else None
            )
            if not user_access_token:
                raise ValidationError(
                    PERSONAL_GITHUB_REQUIRED_MESSAGE,
                    code=GITHUB_LINK_EXISTING_ERROR_PERSONAL_GITHUB_REQUIRED,
                )
            try:
                has_access = GitHubIntegration.verify_user_installation_access(
                    str(source_installation_id), user_access_token
                )
            except requests.RequestException:
                raise ValidationError("Failed to verify installation access")
            if not has_access:
                raise ValidationError(
                    PERSONAL_GITHUB_REQUIRED_MESSAGE,
                    code=GITHUB_LINK_EXISTING_ERROR_PERSONAL_GITHUB_REQUIRED,
                )

            integration = GitHubIntegration.integration_from_installation_id(str(source_installation_id), team.id, user)

            source_login = (existing_install.config or {}).get("connecting_user_github_login")
            if source_login and not (integration.config or {}).get("connecting_user_github_login"):
                integration.config["connecting_user_github_login"] = source_login
                integration.save(update_fields=["config"])
        except ValidationError as exc:
            error_code = _validation_error_code(exc)
            if error_code not in (
                GITHUB_LINK_EXISTING_ERROR_ORPHAN_INSTALLATION,
                GITHUB_LINK_EXISTING_ERROR_PERSONAL_GITHUB_REQUIRED,
            ):
                raise
            oauth_url = build_team_github_oauth_authorize_url(
                user_id=user.id,
                team_id=team.id,
                installation_id=installation_id_str,
                next_url=next_url,
                connect_from=connect_from,
            )
            return TeamGitHubFinishSetupResult(
                next_url=next_url,
                installation_id=installation_id_str,
                oauth_url=oauth_url,
            )

        return TeamGitHubFinishSetupResult(
            next_url=next_url,
            installation_id=installation_id_str,
            integration=integration,
        )

    fresh_token = os.urandom(33).hex()
    github_callback_state.store_unified_authorize_state(
        GitHubAuthorizeState(
            token=fresh_token,
            flow=FlowKind.TEAM_INSTALL,
            user_id=github_callback_state.authenticated_user_id(request),
            team_id=team.id,
            next_url=next_url or None,
        ),
    )
    integration = create_team_github_integration_from_oauth_code(
        request=request,
        user=user,
        team_id=team.id,
        installation_id=installation_id_str,
        state_token=fresh_token,
        code=code,
    )
    return TeamGitHubFinishSetupResult(
        next_url=next_url,
        installation_id=installation_id_str,
        integration=integration,
    )


def refresh_team_github_integration(
    user: User,
    team_id: int,
    installation_id: str,
    *,
    existing: Integration,
) -> Integration:
    try:
        return GitHubIntegration.integration_from_installation_id(installation_id, team_id, user)
    except GitHubInstallationAccessFetchError:
        logger.warning(
            "github_team_setup: failed to refresh integration after update",
            installation_id=installation_id,
            user_id=user.id,
            team_id=team_id,
            exc_info=True,
        )
        invalidate_github_repository_caches_for_installation(installation_id)
        return existing


def build_team_github_oauth_authorize_url(
    *,
    user_id: int,
    team_id: int,
    installation_id: str,
    next_url: str,
    connect_from: str | None,
) -> str:
    if not installation_id:
        raise ValidationError("installation_id is required")

    if not is_valid_github_installation_id(installation_id):
        raise ValidationError("Invalid installation_id")

    if next_url and not is_relative_url(next_url):
        raise ValidationError("next must be a relative path starting with /")

    token = get_random_string(48)
    resolved_connect_from = connect_from if connect_from == "posthog_code" else _connect_from_for_next(next_url)
    authorize_state = GitHubAuthorizeState(
        token=token,
        flow=FlowKind.TEAM_OAUTH,
        user_id=user_id,
        team_id=team_id,
        installation_id=str(installation_id),
        next_url=next_url or None,
        connect_from=resolved_connect_from,
    )
    github_callback_state.store_unified_authorize_state(authorize_state)

    return github_oauth_authorize_url(urlencode({"token": token}))


def authenticated_drf_request(http_request: HttpRequest) -> Request:
    drf_request = Request(http_request)
    auth_result = SessionAuthentication().authenticate(drf_request)
    if auth_result is not None:
        drf_request.user, drf_request.auth = auth_result
    elif http_request.user.is_authenticated:
        mutable_request = cast(Any, drf_request)
        mutable_request._user = http_request.user
        mutable_request._auth = None
    return cast(Request, drf_request)


def link_existing_team_github_integration(
    *,
    user: User,
    organization: Organization,
    team_id: int,
    source_team_id: Any | None,
    installation_id_param: Any | None,
) -> Integration:
    if installation_id_param and not is_valid_github_installation_id(installation_id_param):
        raise ValidationError("Invalid installation_id")

    if source_team_id:
        try:
            source_team_id_int = int(source_team_id)
        except (TypeError, ValueError):
            raise ValidationError("source_team_id must be an integer")

        if not organization.teams.filter(id=source_team_id_int).exists():
            raise ValidationError("Source team not found in your organization")

        qs = Integration.objects.filter(team_id=source_team_id_int, kind="github")
        if installation_id_param:
            qs = qs.for_github_installation_id(str(installation_id_param))

        source = qs.order_by("id").first()
        if source is None:
            raise ValidationError("Source team does not have a GitHub integration")
    elif installation_id_param:
        existing = (
            Integration.objects.filter(
                team__organization_id=organization.id,
                kind="github",
            )
            .for_github_installation_id(str(installation_id_param))
            .order_by("id")
            .first()
        )
        if existing is None:
            raise ValidationError(
                "No team in your organization has this GitHub installation linked",
                code=GITHUB_LINK_EXISTING_ERROR_ORPHAN_INSTALLATION,
            )
        source = existing
    else:
        raise ValidationError("source_team_id or installation_id is required")

    installation_id = (source.config or {}).get("installation_id")
    if not installation_id:
        raise ValidationError("Source integration is missing installation_id")
    installation_id_str = str(installation_id)

    user_github_integration = UserIntegration.objects.filter(user=user, kind="github").order_by("-created_at").first()
    user_access_token = (
        user_github_integration.sensitive_config.get("access_token") if user_github_integration else None
    )
    if not user_access_token:
        raise ValidationError(
            PERSONAL_GITHUB_REQUIRED_MESSAGE,
            code=GITHUB_LINK_EXISTING_ERROR_PERSONAL_GITHUB_REQUIRED,
        )
    try:
        has_access = GitHubIntegration.verify_user_installation_access(str(installation_id), user_access_token)
    except requests.RequestException:
        raise ValidationError("Failed to verify installation access")
    if not has_access:
        raise ValidationError(
            PERSONAL_GITHUB_REQUIRED_MESSAGE,
            code=GITHUB_LINK_EXISTING_ERROR_PERSONAL_GITHUB_REQUIRED,
        )

    existing_target = Integration.objects.first_github_for_team_installation(team_id, installation_id_str)
    if existing_target is not None:
        target_team = Team.objects.get(id=team_id)
        if not github_callback_state.has_team_management_access(user, target_team):
            raise PermissionDenied("You need project admin access to update an existing GitHub integration.")

    instance = GitHubIntegration.integration_from_installation_id(installation_id_str, team_id, user)

    source_login = (source.config or {}).get("connecting_user_github_login")
    if source_login and not (instance.config or {}).get("connecting_user_github_login"):
        instance.config["connecting_user_github_login"] = source_login
        instance.save(update_fields=["config"])

    return instance


def finish_team_setup(http_request) -> FinishResult:
    state_raw = http_request.GET.get("state")
    user = cast(User, http_request.user)
    installation_id = http_request.GET.get("installation_id")
    setup_action = http_request.GET.get("setup_action") or ""
    team_id, next_url = github_callback_state.resolve_github_setup_callback_context(user, state_raw)

    if github_error := http_request.GET.get("error"):
        logger.warning(
            "github_team_setup: GitHub returned error on callback",
            error=github_error,
            description=http_request.GET.get("error_description"),
            user_id=user.id,
        )
        error_code = "access_denied" if github_error == "access_denied" else "github_oauth_error"
        return FinishResult(
            redirect_kind="team_setup",
            next_url=next_url,
            team_id=team_id,
            error=error_code,
        )

    if not installation_id:
        return FinishResult(
            redirect_kind="team_setup",
            next_url=next_url,
            team_id=team_id,
            pending=True,
        )

    installation_id_str = str(installation_id)
    if setup_action == "update" and team_id is None and is_valid_github_installation_id(installation_id):
        existing_for_user = Integration.objects.first_github_for_user_installation(user, installation_id_str)
        if existing_for_user is not None:
            team_id = existing_for_user.team_id

    if team_id is None:
        return FinishResult(
            redirect_kind="team_setup",
            next_url=next_url,
            team_id=team_id,
            error="invalid_state",
        )

    # `resolve_github_setup_callback_context` already filtered team_id by `user.teams`.
    # Permission changes between authorize-click and callback-return (removed from team,
    # team deleted) are rare enough to not warrant a typed error; let them 500.
    team = Team.objects.select_related("organization").get(id=team_id)

    # Adding a new team integration requires only project membership; modifying an existing one
    # (reconnect / settings update) still requires admin. The callback's team_id can come from a
    # user-controlled `next`/`state` param, so a plain member must never alter an integration that
    # already exists — only create the team's first link for this installation. State-token
    # validation downstream still guards against forged callbacks regardless of membership level.
    existing_team_integration = (
        Integration.objects.first_github_for_team_installation(team.id, installation_id_str)
        if is_valid_github_installation_id(installation_id_str)
        else None
    )
    modifying_existing = existing_team_integration is not None or setup_action == "update"
    has_required_access = (
        github_callback_state.has_team_management_access(user, team)
        if modifying_existing
        else github_callback_state.has_team_membership_access(user, team)
    )
    if not has_required_access:
        return FinishResult(
            redirect_kind="team_setup",
            next_url=next_url,
            team_id=team_id,
            error="insufficient_permissions",
        )

    code = http_request.GET.get("code") or None
    request = authenticated_drf_request(http_request)

    if setup_action == "update":
        if not is_valid_github_installation_id(installation_id):
            return FinishResult(
                redirect_kind="team_setup",
                next_url=next_url,
                team_id=team_id,
                error="invalid_installation_id",
            )

        existing = Integration.objects.first_github_for_team_installation(team.id, installation_id_str)
        if existing is not None:
            update_result = finish_team_github_setup_update(
                user=user,
                team_id=team.id,
                request=request,
                installation_id=installation_id_str,
                existing=existing,
                state_raw=state_raw,
                fallback_next_url=next_url,
            )
            return FinishResult(
                redirect_kind="team_setup",
                next_url=str(update_result.next_url),
                team_id=team_id,
                installation_id=update_result.installation_id,
                integration_id=str(update_result.integration.id) if update_result.integration is not None else None,
            )

    try:
        result = execute_team_github_finish_setup(
            user=user,
            team=team,
            request=request,
            installation_id=installation_id_str,
            code=code,
            setup_action=setup_action,
            state_raw=state_raw,
        )
    except ValidationError as exc:
        error_code = _validation_error_code(exc) or "github_install_failed"
        detail: object = exc.detail
        if isinstance(detail, list) and detail:
            error_message = str(detail[0])
        elif isinstance(detail, dict):
            error_message = str(detail)
            for value in detail.values():
                if isinstance(value, list) and value:
                    error_message = str(value[0])
                else:
                    error_message = str(value)
                break
        else:
            error_message = str(detail)
        logger.warning(
            "github_team_setup: finish setup failed",
            error_code=error_code,
            user_id=user.id,
            team_id=team_id,
        )
        return FinishResult(
            redirect_kind="team_setup",
            next_url=next_url,
            team_id=team_id,
            error=error_code,
            error_message=error_message,
        )

    if result.oauth_url:
        return FinishResult(redirect_kind="oauth_url", oauth_url=result.oauth_url)

    success_next = str(result.next_url or redirects.landing_url(next_url, team_id))
    integration_id = str(result.integration.id) if result.integration is not None else None
    return FinishResult(
        redirect_kind="team_setup",
        next_url=success_next,
        team_id=team_id,
        installation_id=str(result.installation_id or installation_id),
        integration_id=integration_id,
    )


# Backwards-compatible alias for integration.py
build_team_oauth_authorize_url = build_team_github_oauth_authorize_url
