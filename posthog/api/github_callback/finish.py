"""Unified GitHub callback finish engine."""

from __future__ import annotations

from django.http import HttpRequest

from posthog.api.github_callback import personal_finish, state, team_finish
from posthog.api.github_callback.personal_state import is_personal_github_setup_state
from posthog.api.github_callback.types import CallbackContext, FinishResult, FlowKind, github_oauth_callback_error_code
from posthog.models.user_integration import UserIntegration


def finish(http_request: HttpRequest, ctx: CallbackContext) -> FinishResult:
    user = http_request.user
    assert user.is_authenticated

    if ctx.github_error:
        error_code = github_oauth_callback_error_code(ctx.github_error)
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

    if ctx.setup_action == "update" and ctx.installation_id:
        installation_id_str = str(ctx.installation_id)
        if ctx.flow == FlowKind.PERSONAL_UPDATE:
            return personal_finish.finish_personal_setup_update(http_request)
        if ctx.flow == FlowKind.TEAM_UPDATE:
            return team_finish.finish_team_setup(http_request)
        if state.has_pending_personal_setup_update(user, installation_id_str):
            return personal_finish.finish_personal_setup_update(http_request)
        if state.has_pending_team_setup_update(user, ctx.state_raw):
            return team_finish.finish_team_setup(http_request)
        team_integration = state.team_integration_for_user_installation(user, installation_id_str)
        has_personal = UserIntegration.objects.filter(
            user=user,
            kind=UserIntegration.IntegrationKind.GITHUB,
            integration_id=installation_id_str,
        ).exists()
        if has_personal:
            return personal_finish.finish_personal_setup_update(http_request)
        if team_integration is not None:
            return team_finish.finish_team_setup_update(http_request, team_integration)

    return team_finish.finish_team_setup(http_request)
