from typing import Literal, cast
from urllib.parse import quote

from django.core.cache import cache
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect, JsonResponse
from django.shortcuts import redirect
from django.views.decorators.http import require_http_methods

from posthog.api.github_callback import finish, redirects, state
from posthog.api.github_callback.personal_state import is_personal_github_setup_state
from posthog.api.github_callback.types import CallbackContext, FlowKind, github_oauth_redirect_uri
from posthog.models import User
from posthog.models.integration import GitHubIntegration, GitHubUserAuthorization


def require_session_or_login_redirect(
    request: HttpRequest,
    *,
    resume_path: str,
) -> HttpResponseRedirect | None:
    if request.user.is_authenticated:
        return None
    return redirect(f"/login?next={quote(resume_path, safe='')}")


def require_session_or_401(request: HttpRequest) -> HttpResponse | None:
    if request.user.is_authenticated:
        return None
    return JsonResponse({"detail": "Authentication credentials were not provided."}, status=401)


def exchange_user_authorization(code: str, *, use_oauth_redirect_uri: bool) -> GitHubUserAuthorization | None:
    if use_oauth_redirect_uri:
        return GitHubIntegration.github_user_from_code(code, redirect_uri=github_oauth_redirect_uri())
    return GitHubIntegration.github_user_from_code(code)


def _parse_callback(request: HttpRequest, entry: Literal["setup_url", "oauth_redirect"]) -> CallbackContext:
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


@require_http_methods(["GET"])
def handle_setup_url(request: HttpRequest) -> HttpResponseRedirect:
    """GitHub App Setup URL — team finish or personal install (same router)."""
    resume_path = request.get_full_path()
    if redirect := require_session_or_login_redirect(request, resume_path=resume_path):
        return redirect

    ctx = _parse_callback(request, "setup_url")
    result = finish.finish(request, ctx)
    return redirects.redirect_from_finish_result(result)


@require_http_methods(["GET"])
def handle_oauth_redirect(request: HttpRequest) -> HttpResponse | HttpResponseRedirect:
    """GitHub User OAuth redirect_uri — personal and team-oauth recovery flows."""
    if response := require_session_or_401(request):
        return response

    ctx = _parse_callback(request, "oauth_redirect")
    result = finish.finish(request, ctx)
    return redirects.redirect_from_finish_result(result)
