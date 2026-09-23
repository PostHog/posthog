"""Shared guard for the `logo_uri` an OAuth client supplies about itself.

Both self-registration paths accept the value from the client, and PostHog renders it as an
`<img src>` on the consent screen and on the auth screens.

PostHog never fetches a logo, so this does not protect PostHog's own egress. It protects the
visitor: the browser makes that request, and a self-hosted deployment renders these pages to
people inside a trusted network. A logo pointing at a loopback, metadata or internal address
would make each of those browsers probe its own network from a PostHog page.
"""

from posthog.security.url_validation import is_url_allowed

# Column limit of `OAuthApplication.logo_uri`.
MAX_LOGO_URI_LENGTH = 2048


def usable_logo_uri(value: object) -> str | None:
    """The logo URI if a browser can load it from a PostHog page, else None.

    Only https survives, because a PostHog page is https and a browser blocks the rest.

    A rejected logo does not fail the registration, because the logo is decorative and the
    client can still complete every OAuth flow without it.
    """
    if not isinstance(value, str) or not value.startswith("https://") or len(value) > MAX_LOGO_URI_LENGTH:
        return None
    allowed, _ = is_url_allowed(value)
    return value if allowed else None
