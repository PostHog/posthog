from typing import Literal, cast

from django.core.cache import cache
from django.http import HttpRequest, HttpResponseRedirect
from django.views.decorators.http import require_http_methods

from posthog.api.github_callback import personal_finish, redirects, state, team_services
from posthog.api.github_callback.types import CallbackContext, FinishResult, FlowKind, is_personal_github_setup_state
from posthog.auth import session_auth_required
from posthog.models import User
from posthog.models.user_integration import UserIntegration
from posthog.views import login_required


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
        if state.has_pending_personal_setup_update(user, ctx.installation_id):
            ctx.flow = FlowKind.PERSONAL_UPDATE

    return ctx


def _is_personal_github_setup_update(user: User, ctx: CallbackContext) -> bool:
    # When state was present and loaded, trust the flow it encodes. Only the explicit
    # personal-update flow should route here — any team-side flow (install, update,
    # oauth recovery) must fall through to finish_team_setup. The UserIntegration
    # fallback below only applies when state is missing (e.g. user opened GitHub
    # directly without going through PostHog UI).
    if ctx.flow is not None:
        return ctx.flow == FlowKind.PERSONAL_UPDATE
    if not ctx.installation_id:
        return False
    return UserIntegration.objects.filter(
        user=user,
        kind=UserIntegration.IntegrationKind.GITHUB,
        integration_id=str(ctx.installation_id),
    ).exists()


def _finish(http_request: HttpRequest, ctx: CallbackContext) -> FinishResult:
    user = http_request.user
    assert user.is_authenticated

    if ctx.github_error:
        error_code = "access_denied" if ctx.github_error == "access_denied" else "github_oauth_error"
        # TEAM_OAUTH recovery failures should land on the project page, not the personal page —
        # the user was trying to set up a team integration. State is still in cache at this point
        # (load_authorize_state is read-only), so we have the team_id and next_url to redirect with.
        if ctx.flow == FlowKind.TEAM_OAUTH and ctx.authorize_state is not None:
            return FinishResult(
                redirect_kind="team_setup",
                next_url=ctx.authorize_state.next_url,
                team_id=ctx.authorize_state.team_id,
                error=error_code,
            )
        if ctx.entry == "oauth_redirect" or is_personal_github_setup_state(ctx.state_raw):
            connect_from = ctx.authorize_state.connect_from if ctx.authorize_state else None
            return FinishResult(redirect_kind="personal_finish", connect_from=connect_from, error=error_code)
        team_id, next_url = state.resolve_github_setup_callback_context(user, ctx.state_raw)
        return FinishResult(
            redirect_kind="team_setup",
            next_url=next_url,
            team_id=team_id,
            error=error_code,
        )

    if ctx.entry == "oauth_redirect" or is_personal_github_setup_state(ctx.state_raw):
        return personal_finish.finish_personal(http_request)

    if ctx.setup_action == "update" and ctx.installation_id and _is_personal_github_setup_update(user, ctx):
        return personal_finish.finish_personal_setup_update(http_request)

    return team_services.finish_team_setup(http_request)


@require_http_methods(["GET"])
@login_required
def github_setup_callback(request: HttpRequest) -> HttpResponseRedirect:
    """GitHub App Setup URL — team finish or personal install."""
    ctx = _parse_callback(request, "setup_url")
    result = _finish(request, ctx)
    return redirects.redirect_from_finish_result(result)


@require_http_methods(["GET"])
@session_auth_required
def github_oauth_callback(request: HttpRequest) -> HttpResponseRedirect:
    """GitHub User OAuth redirect_uri — personal and team-oauth recovery flows."""
    ctx = _parse_callback(request, "oauth_redirect")
    result = _finish(request, ctx)
    return redirects.redirect_from_finish_result(result)
