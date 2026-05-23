import os
from typing import Any, cast
from urllib.parse import parse_qsl, urlparse

from django.core.cache import cache
from django.db.models import Q

from rest_framework.exceptions import ValidationError
from rest_framework.request import Request

from posthog.api.github_callback.types import (
    GITHUB_AUTHORIZE_STATE_CACHE_TTL_SECONDS,
    GITHUB_UNIFIED_AUTHORIZE_CACHE_PREFIX,
    GITHUB_UNIFIED_AUTHORIZE_PENDING_PREFIX,
    PERSONAL_INTEGRATIONS_SETTINGS_PATH,
    FlowKind,
    GitHubAuthorizeState,
)
from posthog.models import User
from posthog.models.integration import Integration


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


def github_installation_id_q(installation_id: str | int) -> Q:
    return Q(config__installation_id=str(installation_id)) | Q(config__installation_id=int(installation_id))


def team_id_from_next_url(next_url: str) -> int | None:
    if not next_url:
        return None
    parsed = urlparse(next_url)
    project_id = dict(parse_qsl(parsed.query)).get("project_id")
    if project_id is not None:
        try:
            return int(project_id)
        except ValueError:
            pass
    path_parts = [part for part in parsed.path.split("/") if part]
    if len(path_parts) >= 2 and path_parts[0] == "project":
        try:
            return int(path_parts[1])
        except ValueError:
            pass
    return None


def team_id_from_authorize_payload(payload: dict[str, Any] | str) -> int | None:
    if not isinstance(payload, dict):
        return None
    raw_team_id = payload.get("team_id")
    if raw_team_id is not None:
        try:
            return int(raw_team_id)
        except (TypeError, ValueError):
            pass
    return team_id_from_next_url(str(payload.get("next") or ""))


def authorize_state_from_payload(token: str, payload: dict[str, Any]) -> GitHubAuthorizeState:
    flow = FlowKind(payload["flow"])
    connect_from = payload.get("connect_from")
    return GitHubAuthorizeState(
        token=token,
        flow=flow,
        user_id=int(payload["user_id"]),
        team_id=int(payload["team_id"])
        if payload.get("team_id") is not None
        else team_id_from_authorize_payload(payload),
        installation_id=str(payload["installation_id"]) if payload.get("installation_id") is not None else None,
        next_url=str(payload["next"]) if payload.get("next") else None,
        connect_from=str(connect_from) if connect_from else None,
    )


def store_unified_authorize_state(state: GitHubAuthorizeState, *, ttl: int | None = None) -> None:
    timeout = ttl or GITHUB_AUTHORIZE_STATE_CACHE_TTL_SECONDS
    payload: dict[str, Any] = {
        "token": state.token,
        "flow": state.flow.value,
        "user_id": state.user_id,
    }
    if state.team_id is not None:
        payload["team_id"] = state.team_id
    if state.installation_id is not None:
        payload["installation_id"] = state.installation_id
    if state.next_url is not None:
        payload["next"] = state.next_url
    if state.connect_from is not None:
        payload["connect_from"] = state.connect_from

    cache.set(unified_authorize_cache_key(state.token), payload, timeout=timeout)
    cache.set(unified_authorize_pending_cache_key(state.user_id), state.token, timeout=timeout)


def store_personal_authorize_state(state: GitHubAuthorizeState) -> None:
    store_unified_authorize_state(state)


def store_github_authorize_state(
    user_id: int,
    token: str,
    next_url: str,
    team_id: int | None = None,
    *,
    flow: FlowKind = FlowKind.TEAM_INSTALL,
) -> None:
    store_unified_authorize_state(
        GitHubAuthorizeState(
            token=token,
            flow=flow,
            user_id=user_id,
            team_id=team_id,
            next_url=next_url or None,
        ),
    )


def peek_github_authorize_state(user_id: int, cached: Any | None = None) -> tuple[str | None, str | None, int | None]:
    if cached is None:
        pending_token = cache.get(unified_authorize_pending_cache_key(user_id))
        if not pending_token:
            return None, None, None
        cached = cache.get(unified_authorize_cache_key(str(pending_token)))
        if not isinstance(cached, dict):
            return None, None, None
    if isinstance(cached, dict):
        token = str(cached.get("token") or "") or None
        next_url = str(cached.get("next") or "") or None
        return token, next_url, team_id_from_authorize_payload(cached)
    return str(cached), None, None


def resolve_github_setup_callback_context(
    user: User,
    state_raw: str | None,
) -> tuple[int | None, str | None]:
    """Reads from both the authorize cache and the GitHub ``state`` query param, preferring the query param."""
    _, cached_next, cached_team_id = peek_github_authorize_state(user.id)

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


def store_personal_manage_callback_state(user_id: int, installation_id: str) -> None:
    token = os.urandom(33).hex()
    store_personal_authorize_state(
        GitHubAuthorizeState(
            token=token,
            flow=FlowKind.PERSONAL_UPDATE,
            user_id=user_id,
            installation_id=str(installation_id),
            next_url=PERSONAL_INTEGRATIONS_SETTINGS_PATH,
        ),
    )


def has_pending_team_setup_update(user: User, state_raw: str | None) -> bool:
    pending_token = cache.get(unified_authorize_pending_cache_key(user.id))
    if pending_token is None:
        return False
    cached = cache.get(unified_authorize_cache_key(str(pending_token)))
    if not isinstance(cached, dict):
        return False

    expected_token = str(cached.get("token") or pending_token)

    if not state_raw:
        return True

    param_token, _ = parse_github_authorize_state_param(state_raw)
    if param_token is None:
        return state_raw == expected_token
    return param_token == expected_token


def load_authorize_state(token: str, *, user_id: int | None = None) -> GitHubAuthorizeState | None:
    unified = cache.get(unified_authorize_cache_key(token))
    if not isinstance(unified, dict):
        return None
    state = authorize_state_from_payload(token, unified)
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


def github_integration_for_installation(team_id: int, installation_id: str) -> Integration | None:
    return (
        Integration.objects.filter(team_id=team_id, kind="github")
        .filter(github_installation_id_q(installation_id))
        .first()
    )


def team_integration_for_user_installation(user: User, installation_id: str) -> Integration | None:
    user_team_ids = user.teams.values_list("id", flat=True)
    return (
        Integration.objects.filter(team_id__in=user_team_ids, kind="github")
        .filter(github_installation_id_q(installation_id))
        .first()
    )


def consume_github_authorize_state(
    request: Request,
    state_raw: str | None,
    *,
    setup_action: str = "",
    code: str | None = None,
) -> tuple[str, str, int | None]:
    user_id = authenticated_user_id(request)
    pending_token = cache.get(unified_authorize_pending_cache_key(user_id))
    cached = cache.get(unified_authorize_cache_key(str(pending_token))) if pending_token else None
    if not isinstance(cached, dict):
        raise ValidationError("Invalid or expired state token", code="invalid_state")

    expected_token = str(cached.get("token") or "")
    cached_next = str(cached.get("next") or "")

    if not state_raw:
        if code is not None or setup_action != "update":
            raise ValidationError("Invalid or expired state token", code="invalid_state")
        param_next = None
    else:
        param_token, param_next = parse_github_authorize_state_param(state_raw)
        if param_token is not None and param_token != expected_token:
            raise ValidationError("Invalid or expired state token", code="invalid_state")

    team_id = team_id_from_authorize_payload(cached)

    cache.delete(unified_authorize_cache_key(expected_token))
    cache.delete(unified_authorize_pending_cache_key(user_id))
    return expected_token, param_next or cached_next, team_id
