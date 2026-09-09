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
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request

from posthog.api.github_callback import (
    redirects,
    state as github_callback_state,
)
from posthog.api.github_callback.install_requests import record_install_request
from posthog.api.github_callback.personal_state import (
    list_user_github_app_installations,
    personal_github_login,
    usable_personal_github_token,
)
from posthog.api.github_callback.types import (
    FinishResult,
    FlowKind,
    GitHubAuthorizeState,
    github_oauth_authorize_url,
    is_valid_github_installation_id,
)
from posthog.auth import SessionAuthentication
from posthog.egress.github.transport import GitHubEgressBudgetExhausted
from posthog.event_usage import report_user_action
from posthog.models import Team
from posthog.models.integration import (
    GitHubInstallationAccess,
    GitHubInstallationAccessFetchError,
    GitHubIntegration,
    GitHubUserAuthorization,
    Integration,
    defer_repository_cache_fields,
    invalidate_github_repository_caches_for_installation,
)
from posthog.models.organization import Organization
from posthog.models.user import User
from posthog.models.user_integration import user_github_integration_from_installation
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

    return link_github_installation_for_user(
        user=user, team_id=team_id, installation_id=installation_id, authorization=authorization
    )


def link_github_installation_for_user(
    *,
    user: User,
    team_id: int,
    installation_id: str,
    authorization: "GitHubUserAuthorization",
) -> Integration:
    """Verify the user controls the installation, then create both GitHub records:
    the team-scoped Integration and the personal UserIntegration.

    Request-free core of the team GitHub link, shared with flows that hold an
    already-exchanged authorization (e.g. agentic provisioning GitHub grants).
    """
    if not is_valid_github_installation_id(installation_id):
        raise ValidationError("Invalid installation_id")
    try:
        has_access = GitHubIntegration.verify_user_installation_access(installation_id, authorization.access_token)
    except (requests.RequestException, GitHubEgressBudgetExhausted):
        logger.warning(
            "github_integration_create: installation ownership check failed",
            installation_id=installation_id,
            user_id=user.id,
            exc_info=True,
        )
        raise ValidationError("Failed to verify installation access", code="installation_verify_failed")
    if not has_access:
        logger.warning(
            "github_integration_create: user does not have access to installation",
            installation_id=installation_id,
            user_id=user.id,
        )
        raise ValidationError("You do not have access to this GitHub installation", code="installation_access_denied")

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


def authorize_link_existing_installation(
    *,
    user: User,
    team: Team,
    source_installation_id: str,
) -> None:
    """Confirm ``user`` may link an installation already present in their org to ``team``.

    The installation is already linked to another team in the same organization, so the org
    already has legitimate access to it. A user with admin access to the target team can therefore
    attach another of the org's own projects to that installation without re-proving personal
    GitHub access, because team admin within the org is sufficient ownership proof. This is what
    lets a second PostHog project reuse a GitHub App that installs only once per org.

    For anyone without team admin access (e.g. a plain member using the explicit link endpoint),
    fall back to proving access with the user's personal GitHub OAuth token, raising
    ``GITHUB_LINK_EXISTING_ERROR_PERSONAL_GITHUB_REQUIRED`` when that proof is missing or fails.
    """
    if github_callback_state.has_team_management_access(user, team):
        return

    user_access_token = usable_personal_github_token(user)
    if not user_access_token:
        raise ValidationError(
            PERSONAL_GITHUB_REQUIRED_MESSAGE,
            code=GITHUB_LINK_EXISTING_ERROR_PERSONAL_GITHUB_REQUIRED,
        )
    try:
        has_access = GitHubIntegration.verify_user_installation_access(source_installation_id, user_access_token)
    except (requests.RequestException, GitHubEgressBudgetExhausted):
        raise ValidationError("Failed to verify installation access")
    if not has_access:
        raise ValidationError(
            PERSONAL_GITHUB_REQUIRED_MESSAGE,
            code=GITHUB_LINK_EXISTING_ERROR_PERSONAL_GITHUB_REQUIRED,
        )


GITHUB_ADOPTION_ADMIN_REQUIRED_MESSAGE = (
    "Linking a GitHub installation that no project has connected yet requires admin access to this "
    "project. Ask a project admin to link it."
)


def adopt_orphan_installation(*, user: User, team: Team, installation_id: str) -> Integration:
    """Create the team's first ``Integration`` row for a GitHub App installation that exists on
    GitHub but was never linked to any PostHog team — e.g. a non-admin clicked "Connect
    organization", GitHub created an install *request*, and a GitHub org admin approved it
    directly on github.com without completing PostHog's callback.

    Introducing a new installation to the org is held to the same bar as a first-time connect
    through the setup callback: PostHog project admin. On top of that, personal GitHub access
    proof is always required — unlike sibling reuse, there's no existing PostHog integration to
    imply the org already has legitimate access, and the admin requirement alone proves nothing
    on the GitHub side. The create/update flows are additionally gated by GitHub itself (only a
    GitHub org admin reaches the callback with a valid installation_id); adoption has no such
    gate, so neither check here can be dropped.
    """
    if not github_callback_state.has_team_management_access(user, team):
        raise ValidationError(
            GITHUB_ADOPTION_ADMIN_REQUIRED_MESSAGE,
            code="github_adoption_admin_required",
        )
    token = usable_personal_github_token(user)
    if token is None:
        raise ValidationError(
            PERSONAL_GITHUB_REQUIRED_MESSAGE,
            code=GITHUB_LINK_EXISTING_ERROR_PERSONAL_GITHUB_REQUIRED,
        )
    try:
        has_access = GitHubIntegration.verify_user_installation_access(installation_id, token)
    except (requests.RequestException, GitHubEgressBudgetExhausted):
        raise ValidationError("Failed to verify installation access")
    if not has_access:
        raise ValidationError("You do not have access to this GitHub installation", code="installation_access_denied")

    instance = GitHubIntegration.integration_from_installation_id(installation_id, team.id, user)

    login = personal_github_login(user)
    if login:
        instance.config["connecting_user_github_login"] = login
        instance.save(update_fields=["config"])

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
        next_url = github_callback_state.consume_github_authorize_state(
            request, state_raw, setup_action="update", code=None, installation_id=installation_id_str
        ).next_url

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

    next_url = github_callback_state.consume_github_authorize_state(
        request, state_raw, setup_action=setup_action, code=code, installation_id=installation_id_str
    ).next_url

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

            authorize_link_existing_installation(
                user=user, team=team, source_installation_id=str(source_installation_id)
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


def _accessible_org_team_ids(user: User, organization: Organization) -> set[int]:
    """Team ids in ``organization`` that ``user`` may actually access.

    ``user.teams`` already honours project-based permissioning (private projects, RBAC roles,
    org admin/owner implicit access), so this is the source-project access boundary that gates
    which installations a user can discover and reuse.
    """
    return set(user.teams.filter(organization_id=organization.id).values_list("id", flat=True))


def _org_linked_github_installation_ids(organization: Organization) -> set[str]:
    """Every GitHub installation id linked to *any* team in ``organization``, including projects the
    current user can't access.

    Used to tell a genuinely orphan installation (no PostHog row anywhere in the org) apart from
    one that's merely linked to a project the caller can't see — the latter must keep raising the
    access error rather than being offered up for adoption, or the access boundary in
    ``_accessible_org_team_ids`` would leak through the adoption path.
    """
    org_github = defer_repository_cache_fields(
        Integration.objects.filter(team__organization_id=organization.id, kind="github")
    )
    return {
        str(installation_id)
        for integration in org_github
        if (installation_id := (integration.config or {}).get("installation_id"))
    }


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

    # Reusing a source project's GitHub access requires access to that project; target-team admin isn't
    # enough. Filter the candidates rather than checking the winner, so this stays in step with what
    # `list_org_github_installations` offers.
    accessible_team_ids = _accessible_org_team_ids(user, organization)

    if source_team_id:
        try:
            source_team_id_int = int(source_team_id)
        except (TypeError, ValueError):
            raise ValidationError("source_team_id must be an integer")

        if source_team_id_int not in accessible_team_ids:
            raise ValidationError("Source team not found in your organization")

        qs = Integration.objects.filter(team_id=source_team_id_int, kind="github")
        if installation_id_param:
            qs = qs.for_github_installation_id(str(installation_id_param))

        source = defer_repository_cache_fields(qs).order_by("id").first()
        if source is None:
            raise ValidationError("Source team does not have a GitHub integration")
    elif installation_id_param:
        installation_id_str = str(installation_id_param)
        existing = (
            defer_repository_cache_fields(
                Integration.objects.filter(
                    team__organization_id=organization.id,
                    team_id__in=accessible_team_ids,
                    kind="github",
                ).for_github_installation_id(installation_id_str)
            )
            .order_by("id")
            .first()
        )
        if existing is None:
            if installation_id_str in _org_linked_github_installation_ids(organization):
                # Linked to a team elsewhere in the org that this user can't access — not an orphan,
                # just invisible to them. Falling through to adoption here would let personal GitHub
                # access override the project access boundary `_accessible_org_team_ids` enforces.
                raise ValidationError(
                    "No team in your organization has this GitHub installation linked",
                    code=GITHUB_LINK_EXISTING_ERROR_ORPHAN_INSTALLATION,
                )
            # No PostHog team anywhere in the org has this installation linked. It may still be
            # installed on GitHub — e.g. approved by a GitHub org admin without completing PostHog's
            # callback. Adoption re-proves personal access rather than raising outright.
            target_team = organization.teams.filter(id=team_id).first()
            if target_team is None:
                raise ValidationError("Target team not found in your organization")
            return adopt_orphan_installation(user=user, team=target_team, installation_id=installation_id_str)
        source = existing
    else:
        # No source specified: auto-resolve the org's existing GitHub installation. This backs the
        # one-click "Link existing installation" UI, where a second project reuses the org's single
        # install without the caller having to know a sibling team id or the installation id.
        org_github = (
            Integration.objects.filter(
                team__organization_id=organization.id, team_id__in=accessible_team_ids, kind="github"
            )
            .exclude(team_id=team_id)
            .order_by("id")
        )
        distinct_installation_ids = {
            str(config_installation_id)
            for integration in defer_repository_cache_fields(org_github)
            if (config_installation_id := (integration.config or {}).get("installation_id"))
        }
        if not distinct_installation_ids:
            raise ValidationError(
                "No team in your organization has a GitHub installation to link",
                code=GITHUB_LINK_EXISTING_ERROR_ORPHAN_INSTALLATION,
            )
        if len(distinct_installation_ids) > 1:
            raise ValidationError(
                "Your organization has multiple GitHub installations; specify which one to link via installation_id"
            )
        source = org_github.for_github_installation_id(next(iter(distinct_installation_ids))).first()
        if source is None:
            raise ValidationError(
                "No team in your organization has a GitHub installation to link",
                code=GITHUB_LINK_EXISTING_ERROR_ORPHAN_INSTALLATION,
            )

    installation_id = (source.config or {}).get("installation_id")
    if not installation_id:
        raise ValidationError("Source integration is missing installation_id")

    target_team = organization.teams.filter(id=team_id).first()
    if target_team is None:
        raise ValidationError("Target team not found in your organization")
    authorize_link_existing_installation(user=user, team=target_team, source_installation_id=str(installation_id))

    instance = GitHubIntegration.integration_from_installation_id(str(installation_id), team_id, user)

    source_login = (source.config or {}).get("connecting_user_github_login")
    if source_login and not (instance.config or {}).get("connecting_user_github_login"):
        instance.config["connecting_user_github_login"] = source_login
        instance.save(update_fields=["config"])

    return instance


def list_org_github_installations(
    *,
    user: User,
    organization: Organization,
    exclude_team_id: int | None = None,
) -> list[dict[str, Any]]:
    """List the distinct GitHub App installations ``user`` can link to a project in ``organization``.

    A GitHub App installs once per org, so when an org has more than one installation the caller
    can't rely on the single-install auto-resolve path in ``link_existing_team_github_integration``.
    This enumerates the installations so the UI can offer a picker and pass an explicit
    ``installation_id``. The first integration seen for each installation id (deterministic
    ``order_by("id")``) provides the representative account metadata and source team.

    Only installations linked to source projects the user can access are returned as sibling
    entries (``source_team_id`` set) — mirroring the access boundary enforced in
    ``link_existing_team_github_integration`` so the picker never surfaces an installation the user
    couldn't actually link that way.

    Installations visible to the user's own personal GitHub token but not yet linked to any team in
    the org are also included, with ``source_team_id: None`` — these are adoptable orphans (see
    ``adopt_orphan_installation``). Entries already present as a sibling installation are not
    duplicated.
    """
    accessible_team_ids = _accessible_org_team_ids(user, organization)
    org_github = defer_repository_cache_fields(
        Integration.objects.filter(team__organization_id=organization.id, kind="github")
    ).order_by("id")

    # One pass over the org's rows yields both the sibling entries and the org-wide linked set the
    # adoption merge below excludes against, instead of two near-identical queries.
    installations: dict[str, dict[str, Any]] = {}
    org_linked_installation_ids: set[str] = set()
    for integration in org_github:
        config = integration.config or {}
        raw_installation_id = config.get("installation_id")
        if not raw_installation_id:
            continue
        installation_id = str(raw_installation_id)
        org_linked_installation_ids.add(installation_id)
        if integration.team_id not in accessible_team_ids or integration.team_id == exclude_team_id:
            continue
        if installation_id in installations:
            continue
        account = config.get("account") or {}
        installations[installation_id] = {
            "installation_id": installation_id,
            "account_name": account.get("name") or config.get("connecting_user_github_login"),
            "account_type": account.get("type"),
            "source_team_id": integration.team_id,
        }

    personal_installations = list_user_github_app_installations(user)
    for raw_installation in personal_installations or []:
        installation_id = str(raw_installation.get("id"))
        # Skip anything already linked in the org, even to a project this user can't access — those
        # aren't orphans, and offering them here would advertise an adoption that link_existing then
        # has to refuse.
        if installation_id in installations or installation_id in org_linked_installation_ids:
            continue
        account = raw_installation.get("account") or {}
        installations[installation_id] = {
            "installation_id": installation_id,
            "account_name": account.get("login"),
            "account_type": account.get("type"),
            "source_team_id": None,
        }

    return list(installations.values())


def _report_install_pending(user: User, team_id: int | None, setup_action: str) -> None:
    """GitHub sends the user back with no ``installation_id`` when the install did not complete.

    Either they asked an organization owner to approve it (``setup_action=request``), or they left
    the install screen. Neither case writes a row anywhere, so this event is the only trace the
    attempt leaves. The approval-requested case is the one that matters, because owner approval can
    take days and nothing else records that the wait started.

    Reported only when the callback resolved to a team the user belongs to. Without that, a bare
    ``/integrations/github/callback/?setup_action=request`` would record an approval request against
    whichever project the user happens to have open, since ``report_user_action`` falls back to
    ``user.current_team``.
    """
    if team_id is None:
        return

    team = Team.objects.filter(id=team_id).first()
    if team is None:
        return

    try:
        report_user_action(
            user,
            "integration install pending",
            {
                "integration_kind": "github",
                # Kept raw as well as derived so an unfamiliar setup_action shows up rather than
                # silently folding into the "abandoned" side of the boolean.
                "setup_action": setup_action or None,
                "requested_approval": setup_action == "request",
            },
            team=team,
        )
    except Exception:
        # The pending redirect is the graceful outcome of an install that did not complete. Letting a
        # capture failure raise would turn it into an error page for a callback that is otherwise fine.
        logger.exception("github_team_setup: failed to report pending install", team_id=team_id, user_id=user.id)


def finish_team_setup(http_request) -> FinishResult:
    state_raw = http_request.GET.get("state")
    user = cast(User, http_request.user)
    installation_id = http_request.GET.get("installation_id")
    setup_action = http_request.GET.get("setup_action") or ""
    code = http_request.GET.get("code")
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
        _report_install_pending(user, team_id, setup_action)
        # An abandoned install lands here too, as does a bare cross-site `?setup_action=request`
        # link, since this is also where callbacks with no valid state fall through. No webhook can
        # ever resolve either, so a durable row needs both a real request and this user's own state.
        authorize_state = github_callback_state.callback_authorize_state(user.id, state_raw)
        if setup_action == "request" and authorize_state is not None:
            record_install_request(user, code)
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
