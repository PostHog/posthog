"""Shared guard for the `logo_uri` an OAuth client supplies about itself.

Both self-registration paths accept the value from the client, and PostHog renders it on the
consent screen and on the auth screens.

The guard is deliberately cheap. PostHog never fetches a logo itself, so there is no
server-side request to protect: the browser loads it, from a page that already sets
`referrerPolicy="no-referrer"`. Resolving the host here would add DNS work to an
unauthenticated endpoint and buy nothing.
"""

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
    return value
