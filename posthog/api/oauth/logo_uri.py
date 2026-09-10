"""Shared guard for the `logo_uri` an OAuth client supplies about itself.

Both self-registration paths accept the value from the client, and PostHog renders it on the
consent screen and on the auth screens. A logo that is not an https URL cannot load on those
pages, and one that resolves to an internal address turns each render into an SSRF probe.
"""

from posthog.security.url_validation import is_url_allowed

# Column limit of `OAuthApplication.logo_uri`.
MAX_LOGO_URI_LENGTH = 2048


def usable_logo_uri(value: object) -> str | None:
    """The logo URI if a browser can load it from a PostHog page, else None.

    A rejected logo does not fail the registration, because the logo is decorative and the
    client can still complete every OAuth flow without it.
    """
    if not isinstance(value, str) or not value.startswith("https://") or len(value) > MAX_LOGO_URI_LENGTH:
        return None
    allowed, _ = is_url_allowed(value)
    return value if allowed else None
