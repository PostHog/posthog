"""Parse GitHub callback HTTP requests into CallbackContext."""

from __future__ import annotations

from typing import cast

from django.core.cache import cache
from django.http import HttpRequest

from posthog.api.github_callback import state
from posthog.api.github_callback.personal_state import is_personal_github_setup_state
from posthog.api.github_callback.types import CallbackContext, CallbackEntry, FlowKind
from posthog.models import User


def parse_callback(request: HttpRequest, entry: CallbackEntry) -> CallbackContext:
    state_raw = request.GET.get("state")
    ctx = CallbackContext(
        entry=entry,
        resume_path=request.get_full_path(),
        installation_id=request.GET.get("installation_id"),
        setup_action=request.GET.get("setup_action") or None,
        code=request.GET.get("code") or None,
        state_raw=state_raw,
        github_error=request.GET.get("error"),
        github_error_description=request.GET.get("error_description"),
    )

    if not request.user.is_authenticated:
        return ctx

    user = cast(User, request.user)
    token: str | None = None
    if state_raw:
        token, _ = state.parse_github_authorize_state_param(state_raw)
    if token is None:
        pending_token = cache.get(state.unified_authorize_pending_cache_key(user.id))
        if pending_token is not None:
            token = str(pending_token)

    if token:
        ctx.authorize_state = state.load_authorize_state(token, user_id=user.id)
        if ctx.authorize_state is not None:
            ctx.flow = ctx.authorize_state.flow
            return ctx

    if entry == "setup_url" and is_personal_github_setup_state(state_raw):
        ctx.flow = FlowKind.PERSONAL_INSTALL
    elif entry == "setup_url" and ctx.setup_action == "update":
        if state.has_pending_team_setup_update(user, state_raw):
            ctx.flow = FlowKind.TEAM_UPDATE
        elif state.has_pending_personal_setup_update(user, ctx.installation_id):
            ctx.flow = FlowKind.PERSONAL_UPDATE

    return ctx
