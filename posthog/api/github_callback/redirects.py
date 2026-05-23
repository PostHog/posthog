from urllib.parse import parse_qsl, urlencode, urlparse

from django.http import HttpResponseRedirect
from django.shortcuts import redirect

from posthog.api.github_callback.types import (
    ACCOUNT_CONNECTED_GITHUB_INTEGRATION_PATH,
    MOBILE_GITHUB_CALLBACK_URL,
    PERSONAL_INTEGRATIONS_SETTINGS_PATH,
    FinishResult,
    github_integrations_settings_path,
)
from posthog.utils import is_relative_url


class _AppDeepLinkRedirect(HttpResponseRedirect):
    """Redirect that also permits the mobile app's custom ``posthog://`` scheme."""

    allowed_schemes = [*HttpResponseRedirect.allowed_schemes, "posthog"]


def append_query_params(url: str, params: dict[str, str]) -> str:
    if not params:
        return url
    parsed = urlparse(url)
    merged = dict(parse_qsl(parsed.query))
    merged.update(params)
    query = urlencode(merged)
    fragment = f"#{parsed.fragment}" if parsed.fragment else ""
    return f"{parsed.path}{('?' + query) if query else ''}{fragment}"


def landing_url(next_url: str | None, team_id: int | None) -> str:
    if next_url and is_relative_url(next_url):
        return next_url
    if team_id is not None:
        return github_integrations_settings_path(team_id)
    return "/settings/environment-integrations"


def team_setup_redirect(
    *,
    next_url: str | None,
    team_id: int | None,
    error: str | None = None,
    error_message: str | None = None,
    installation_id: str | None = None,
    integration_id: str | None = None,
    pending: bool = False,
) -> HttpResponseRedirect:
    target = landing_url(next_url, team_id)
    params: dict[str, str] = {}

    if pending:
        params["github_install_pending"] = "1"

    if error:
        if ACCOUNT_CONNECTED_GITHUB_INTEGRATION_PATH in target:
            params["error"] = error
        else:
            params["github_setup_error"] = error
        if error_message:
            params["error_message"] = error_message
    else:
        if installation_id:
            params["installation_id"] = installation_id
        if integration_id:
            params["integration_id"] = integration_id

    return redirect(append_query_params(target, params))


def personal_finish_redirect(connect_from: str | None, *, error: str | None = None) -> HttpResponseRedirect:
    app_base_urls: dict[str, str] = {
        "posthog_mobile": MOBILE_GITHUB_CALLBACK_URL,
        "posthog_code": ACCOUNT_CONNECTED_GITHUB_INTEGRATION_PATH,
    }
    if connect_from in app_base_urls:
        params = {"provider": "github"}
        if error:
            params["error"] = error
        return _AppDeepLinkRedirect(f"{app_base_urls[connect_from]}?{urlencode(params)}")
    if error:
        return redirect(f"{PERSONAL_INTEGRATIONS_SETTINGS_PATH}?github_link_error={error}")
    return redirect(f"{PERSONAL_INTEGRATIONS_SETTINGS_PATH}?github_link_success=1")


def team_oauth_success_redirect(
    *,
    next_url: str | None,
    installation_id: str,
    integration_id: str,
) -> HttpResponseRedirect:
    target = next_url or PERSONAL_INTEGRATIONS_SETTINGS_PATH
    return redirect(
        append_query_params(
            target,
            {
                "installation_id": installation_id,
                "integration_id": integration_id,
            },
        )
    )


def redirect_from_finish_result(result: FinishResult) -> HttpResponseRedirect:
    if result.redirect_kind == "oauth_url" and result.oauth_url:
        return redirect(result.oauth_url)
    if result.redirect_kind == "team_oauth_success":
        assert result.installation_id and result.integration_id
        return team_oauth_success_redirect(
            next_url=result.next_url,
            installation_id=result.installation_id,
            integration_id=result.integration_id,
        )
    if result.redirect_kind == "personal_finish":
        return personal_finish_redirect(result.connect_from, error=result.error)
    return team_setup_redirect(
        next_url=result.next_url,
        team_id=result.team_id,
        error=result.error,
        error_message=result.error_message,
        installation_id=result.installation_id,
        integration_id=result.integration_id,
        pending=result.pending,
    )
