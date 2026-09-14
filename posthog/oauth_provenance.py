"""Provenance checks on the OAuth credential a request arrived with.

Several first-party surfaces share one OAuth application, so the client id alone can't
tell them apart. These helpers read the properties that can: which application minted the
token, whether it carries the server-side-only `internal_run:read` marker, and whether it
came from a real consent flow.

`posthog.auth` is imported inside the functions rather than at module level: `posthog.auth`
pulls in enough of the model layer that importing it here would cycle back through
`posthog.event_usage`, which is one of this module's callers.
"""

from posthog.models.oauth import OAuthRefreshToken
from posthog.temporal.oauth import POSTHOG_DESKTOP_OAUTH_CLIENT_IDS

# Minted server-side only, so its presence proves the token was not obtained by a person
# through the consent flow. See INTERNAL_SCOPES in posthog/temporal/oauth.py.
INTERNAL_RUN_SCOPE = "internal_run:read"


def get_oauth_access_token(request) -> object | None:
    """The OAuth access token backing this request, or None if it authenticated some other way."""
    from posthog.auth import OAuthAccessTokenAuthentication  # noqa: PLC0415 — circular via posthog.event_usage

    authenticator = getattr(request, "successful_authenticator", None)
    if not isinstance(authenticator, OAuthAccessTokenAuthentication):
        return None
    return getattr(authenticator, "access_token", None)


def get_oauth_client_id(request) -> str | None:
    application = getattr(get_oauth_access_token(request), "application", None)
    return getattr(application, "client_id", None)


def is_first_party_oauth_client(request) -> bool:
    """Whether the token was minted against an OAuth application PostHog controls.

    The MCP consumer header is caller-settable, so a third party can declare itself `slack`
    or `posthog_ai`. Requiring one of our own applications is what makes that header
    trustworthy enough to attribute a surface from.
    """
    return get_oauth_client_id(request) in POSTHOG_DESKTOP_OAUTH_CLIENT_IDS


def is_interactive_desktop_grant(request) -> bool:
    """Whether this request carries a PostHog Desktop token a person consented to.

    The Electron app, the cloud coding agent, and the Slack app all authenticate against the
    same OAuth application, so three things have to line up: that application, the absence of
    the server-minted `internal_run:read` marker, and refresh-token lineage proving a consent
    flow happened. Sandbox tokens fail the second check before the third does any query.
    """
    access_token = get_oauth_access_token(request)
    if access_token is None or not is_first_party_oauth_client(request):
        return False
    scopes = set((getattr(access_token, "scope", "") or "").split())
    if INTERNAL_RUN_SCOPE in scopes:
        return False
    return _has_authorization_flow_lineage(access_token)


def _has_authorization_flow_lineage(access_token: object) -> bool:
    if getattr(access_token, "source_refresh_token_id", None) is not None:
        return True
    access_token_id = getattr(access_token, "id", None)
    if access_token_id is None:
        return False
    return OAuthRefreshToken.objects.filter(access_token_id=access_token_id).exists()
