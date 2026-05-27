"""Post-callback redirect helpers for the personal GitHub linking flow."""

from urllib.parse import urlencode

from django.http import HttpResponseRedirect
from django.shortcuts import redirect

from posthog.api.github_callback.types import MOBILE_GITHUB_CALLBACK_URL

PERSONAL_INTEGRATIONS_SETTINGS_PATH = "/settings/user-personal-integrations"
ACCOUNT_CONNECTED_GITHUB_INTEGRATION_PATH = "/account-connected/github-integration"


class AppDeepLinkRedirect(HttpResponseRedirect):
    """Redirect that also permits the mobile app's custom ``posthog://`` scheme.

    Django's default ``HttpResponseRedirect`` rejects non-web schemes as unsafe
    (``DisallowedRedirect``). The target here is a hardcoded first-party deep
    link, not user input, so allowing the extra scheme is safe.
    """

    allowed_schemes = [*HttpResponseRedirect.allowed_schemes, "posthog"]


def final_github_redirect(connect_from: str | None, *, error: str | None = None) -> HttpResponseRedirect:
    """Pick the post-OAuth destination based on which client started the flow.

    - ``posthog_mobile`` → the app's ``posthog://`` deep link so the in-app
      browser auto-closes.
    - ``posthog_code`` → the web ``/account-connected`` page that the desktop app
      intercepts via its own deep link.
    - anything else (web UI) → the personal integrations settings page.
    """
    app_base_urls: dict[str, str] = {
        "posthog_mobile": MOBILE_GITHUB_CALLBACK_URL,
        "posthog_code": ACCOUNT_CONNECTED_GITHUB_INTEGRATION_PATH,
    }
    if connect_from in app_base_urls:
        params = {"provider": "github"}
        if error:
            params["error"] = error
        return AppDeepLinkRedirect(f"{app_base_urls[connect_from]}?{urlencode(params)}")
    if error:
        return redirect(f"{PERSONAL_INTEGRATIONS_SETTINGS_PATH}?github_link_error={error}")
    return redirect(f"{PERSONAL_INTEGRATIONS_SETTINGS_PATH}?github_link_success=1")
