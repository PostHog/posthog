from urllib.parse import parse_qsl, urlencode, urlparse

from django.http import HttpResponseRedirect
from django.shortcuts import redirect

from posthog.api.github_callback.types import (
    ACCOUNT_CONNECTED_GITHUB_INTEGRATION_PATH,
    MOBILE_GITHUB_CALLBACK_URL,
    PERSONAL_INTEGRATIONS_SETTINGS_PATH,
    FinishResult,
)
from posthog.utils import is_relative_url


class _AppDeepLinkRedirect(HttpResponseRedirect):
    """Redirect that also permits the mobile app's custom ``posthog://`` scheme."""

    allowed_schemes = [*HttpResponseRedirect.allowed_schemes, "posthog"]


def _append_query_params(url: str, params: dict[str, str]) -> str:
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
        return f"/project/{team_id}/integrations/github"
    return "/integrations/github"


def redirect_from_finish_result(result: FinishResult) -> HttpResponseRedirect:
    if result.redirect_kind == "oauth_url" and result.oauth_url:
        return redirect(result.oauth_url)

    if result.redirect_kind == "team_oauth_success":
        assert result.installation_id and result.integration_id
        target = result.next_url or PERSONAL_INTEGRATIONS_SETTINGS_PATH
        return redirect(
            _append_query_params(
                target,
                {
                    "installation_id": result.installation_id,
                    "integration_id": result.integration_id,
                },
            )
        )

    if result.redirect_kind == "personal_finish":
        app_base_urls: dict[str, str] = {
            "posthog_mobile": MOBILE_GITHUB_CALLBACK_URL,
            "posthog_code": ACCOUNT_CONNECTED_GITHUB_INTEGRATION_PATH,
            # Slack lands on the same web page; the ``connect_from`` marker tells it to bounce back
            # to the Slack app (deep link) rather than the desktop app.
            "slack": ACCOUNT_CONNECTED_GITHUB_INTEGRATION_PATH,
        }
        if result.connect_from in app_base_urls:
            app_params = {"provider": "github"}
            if result.connect_from == "slack":
                app_params["connect_from"] = "slack"
            if result.error:
                app_params["error"] = result.error
            return _AppDeepLinkRedirect(f"{app_base_urls[result.connect_from]}?{urlencode(app_params)}")
        if result.error:
            return redirect(f"{PERSONAL_INTEGRATIONS_SETTINGS_PATH}?github_link_error={result.error}")
        return redirect(f"{PERSONAL_INTEGRATIONS_SETTINGS_PATH}?github_link_success=1")

    target = landing_url(result.next_url, result.team_id)
    params: dict[str, str] = {}

    if result.pending:
        params["github_install_pending"] = "1"

    if result.error:
        if ACCOUNT_CONNECTED_GITHUB_INTEGRATION_PATH in target:
            params["error"] = result.error
        else:
            params["github_setup_error"] = result.error
        if result.error_message:
            params["error_message"] = result.error_message
    else:
        if result.installation_id:
            params["installation_id"] = result.installation_id
        if result.integration_id:
            params["integration_id"] = result.integration_id

    return redirect(_append_query_params(target, params))
