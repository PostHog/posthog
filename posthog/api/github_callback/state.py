from typing import cast
from urllib.parse import parse_qsl

from django.core.cache import cache

from rest_framework.exceptions import ValidationError
from rest_framework.request import Request

from posthog.api.github_callback.types import (
    GITHUB_AUTHORIZE_STATE_CACHE_TTL_SECONDS,
    GITHUB_UNIFIED_AUTHORIZE_CACHE_PREFIX,
    GITHUB_UNIFIED_AUTHORIZE_PENDING_PREFIX,
    FlowKind,
    GitHubAuthorizeState,
    team_id_from_next_url,
)
from posthog.models import Team, User
from posthog.models.organization import OrganizationMembership
from posthog.user_permissions import UserPermissions


def parse_github_authorize_state_param(state_raw: str | None) -> tuple[str | None, str | None]:
    if not state_raw:
        return None, None
    parsed = dict(parse_qsl(state_raw))
    if "token" in parsed:
        return parsed.get("token"), parsed.get("next")
    return state_raw, None


def unified_authorize_cache_key(token: str) -> str:
    return f"{GITHUB_UNIFIED_AUTHORIZE_CACHE_PREFIX}{token}"


def unified_authorize_pending_cache_key(user_id: int) -> str:
    return f"{GITHUB_UNIFIED_AUTHORIZE_PENDING_PREFIX}{user_id}"


def authenticated_user_id(request: Request) -> int:
    if not request.user.is_authenticated:
        raise ValidationError("Authentication required", code="invalid_state")
    return cast(User, request.user).id


def store_unified_authorize_state(state: GitHubAuthorizeState, *, ttl: int | None = None) -> None:
    timeout = ttl or GITHUB_AUTHORIZE_STATE_CACHE_TTL_SECONDS
    cache.set(unified_authorize_cache_key(state.token), state.cache_payload(), timeout=timeout)
    cache.set(unified_authorize_pending_cache_key(state.user_id), state.token, timeout=timeout)


def has_team_management_access(user: User, team: Team) -> bool:
    """Whether ``user`` may create or modify a team-level integration for ``team``.

    Mirrors ``TeamMemberStrictManagementPermission`` (which gates integration setup on the
    DRF side) for these plain Django callback views: writing a team integration requires
    admin-level effective access, not mere membership. The callback's ``team_id`` can be
    derived from a user-controlled ``next``/``state`` param, so a bare membership check would
    let any project member attach an integration that initiation reserves for admins.
    """
    level = UserPermissions(user).team(team).effective_membership_level
    return level is not None and level >= OrganizationMembership.Level.ADMIN


def resolve_github_setup_callback_context(
    user: User,
    state_raw: str | None,
) -> tuple[int | None, str | None]:
    """Reads from both the authorize cache and the GitHub ``state`` query param, preferring the query param."""
    cached_next: str | None = None
    cached_team_id: int | None = None

    pending_token = cache.get(unified_authorize_pending_cache_key(user.id))
    if pending_token:
        cached = cache.get(unified_authorize_cache_key(str(pending_token)))
        if isinstance(cached, dict):
            token = str(cached.get("token") or "") or None
            authorize_state = GitHubAuthorizeState.try_from_cache(token, cached) if token else None
            if authorize_state is None:
                cached_next = str(cached.get("next") or "") or None
                cached_team_id = team_id_from_next_url(cached_next or "")
            else:
                cached_next = authorize_state.next_url
                cached_team_id = authorize_state.team_id

    team_id = cached_team_id
    next_url = cached_next

    if state_raw:
        _, state_next = parse_github_authorize_state_param(state_raw)
        if state_next:
            next_url = state_next
        if team_id is None and state_next:
            team_id = team_id_from_next_url(state_next)

    if team_id is None and next_url:
        team_id = team_id_from_next_url(next_url)

    if team_id is not None and not user.teams.filter(id=team_id).exists():
        team_id = None

    return team_id, next_url


def has_pending_personal_setup_update(user: User, installation_id: str | None) -> bool:
    pending_token = cache.get(unified_authorize_pending_cache_key(user.id))
    if pending_token is None:
        return False
    authorize_state = load_authorize_state(str(pending_token), user_id=user.id)
    if authorize_state is None or authorize_state.flow != FlowKind.PERSONAL_UPDATE:
        return False
    if installation_id is None:
        return True
    if authorize_state.installation_id is None:
        return True
    return str(authorize_state.installation_id) == str(installation_id)


def load_authorize_state(token: str, *, user_id: int | None = None) -> GitHubAuthorizeState | None:
    unified = cache.get(unified_authorize_cache_key(token))
    if not isinstance(unified, dict):
        return None
    state = GitHubAuthorizeState.try_from_cache(token, unified)
    if state is None:
        return None
    if user_id is not None and state.user_id != user_id:
        return None
    return state


def consume_authorize_state(token: str, *, user_id: int | None = None) -> GitHubAuthorizeState | None:
    state = load_authorize_state(token, user_id=user_id)
    if state is None:
        return None
    cache.delete(unified_authorize_cache_key(token))
    if user_id is not None:
        pending = cache.get(unified_authorize_pending_cache_key(user_id))
        if pending == token:
            cache.delete(unified_authorize_pending_cache_key(user_id))
    return state


def consume_github_authorize_state(
    request: Request,
    state_raw: str | None,
    *,
    setup_action: str = "",
    code: str | None = None,
    installation_id: str | None = None,
) -> tuple[str, str, int | None]:
    user_id = authenticated_user_id(request)
    pending_token = cache.get(unified_authorize_pending_cache_key(user_id))
    cached = cache.get(unified_authorize_cache_key(str(pending_token))) if pending_token else None
    if not isinstance(cached, dict):
        raise ValidationError("Invalid or expired state token", code="invalid_state")

    expected_token = str(cached.get("token") or "")
    cached_next = str(cached.get("next") or "")

    if not state_raw:
        # State-less update callbacks must consume a TEAM_UPDATE pending record — otherwise an
        # attacker could seed any pending state (e.g. TEAM_INSTALL) and trigger a silent link.
        if code is not None or setup_action != "update" or cached.get("flow") != FlowKind.TEAM_UPDATE.value:
            raise ValidationError("Invalid or expired state token", code="invalid_state")
        param_next = None
    else:
        param_token, param_next = parse_github_authorize_state_param(state_raw)
        if param_token is not None and param_token != expected_token:
            raise ValidationError("Invalid or expired state token", code="invalid_state")

    cached_state = GitHubAuthorizeState.try_from_cache(expected_token, cached)

    # Bind the callback to the installation the seeded state intended. The callback's
    # `installation_id` is taken from the user-controlled query string, so without this a member
    # who learns a sibling installation ID could swap it in and have an admin's pending update flow
    # link that installation into this team. Raise before consuming so a genuine callback still works.
    if cached_state is not None and cached_state.installation_id is not None:
        if installation_id is None or str(installation_id) != str(cached_state.installation_id):
            raise ValidationError("Invalid or expired state token", code="invalid_state")

    team_id = cached_state.team_id if cached_state is not None else team_id_from_next_url(cached_next)

    cache.delete(unified_authorize_cache_key(expected_token))
    cache.delete(unified_authorize_pending_cache_key(user_id))
    return expected_token, param_next or cached_next, team_id
