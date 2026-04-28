from datetime import timedelta
from typing import Literal

from django.utils import timezone

from posthog.models import OAuthAccessToken, OAuthApplication
from posthog.models.utils import generate_random_oauth_access_token
from posthog.utils import get_instance_region

ARRAY_APP_CLIENT_ID_US = "HCWoE0aRFMYxIxFNTTwkOORn5LBjOt2GVDzwSw5W"
ARRAY_APP_CLIENT_ID_EU = "AIvijgMS0dxKEmr5z6odvRd8Pkh5vts3nPTzgzU9"
ARRAY_APP_CLIENT_ID_DEV = "DC5uRLVbGI02YQ82grxgnK6Qn12SXWpCqdPb60oZ"

McpScopePreset = Literal["read_only", "full"]


# Scopes matching the MCP server's OAUTH_SCOPES_SUPPORTED (services/mcp/src/lib/constants.ts),
# excluding OAuth auth scopes (openid, profile, email, introspection).
MCP_READ_SCOPES: list[str] = [
    "action:read",
    "cohort:read",
    "dashboard:read",
    "error_tracking:read",
    "event_definition:read",
    "experiment:read",
    "feature_flag:read",
    "hog_flow:read",
    "insight:read",
    "insight_variable:read",
    "llm_prompt:read",
    "logs:read",
    "organization:read",
    "project:read",
    "property_definition:read",
    "query:read",
    "survey:read",
    "user:read",
    "warehouse_table:read",
    "warehouse_view:read",
]

MCP_WRITE_SCOPES: list[str] = [
    "action:write",
    "cohort:write",
    "dashboard:write",
    "error_tracking:write",
    "event_definition:write",
    "experiment:write",
    "feature_flag:write",
    "insight:write",
    "insight_variable:write",
    "llm_prompt:write",
    "survey:write",
]

INTERNAL_SCOPES: list[str] = [
    "task:write",
    "llm_gateway:read",
]

TOKEN_EXPIRATION_SECONDS = 60 * 60 * 6  # 6 hours

PosthogMcpScopes = McpScopePreset | list[str]

MCP_SCOPE_PRESETS = ("read_only", "full")


def resolve_scopes(scopes: PosthogMcpScopes = "read_only", *, include_internal_scopes: bool = True) -> list[str]:
    internal = list(INTERNAL_SCOPES) if include_internal_scopes else []
    if isinstance(scopes, str):
        if scopes == "full":
            return [*MCP_READ_SCOPES, *MCP_WRITE_SCOPES, *internal]
        return [*MCP_READ_SCOPES, *internal]
    return [*scopes, *internal]


def has_write_scopes(scopes: PosthogMcpScopes) -> bool:
    if isinstance(scopes, str):
        return scopes == "full"
    return any(s in MCP_WRITE_SCOPES for s in scopes)


def get_array_app() -> OAuthApplication:
    region = get_instance_region()
    if region == "EU":
        client_id = ARRAY_APP_CLIENT_ID_EU
    elif region == "US":
        client_id = ARRAY_APP_CLIENT_ID_US
    else:
        client_id = ARRAY_APP_CLIENT_ID_DEV

    try:
        return OAuthApplication.objects.get(client_id=client_id)
    except OAuthApplication.DoesNotExist as err:
        raise RuntimeError(f"Array app not found for region {region} (client_id={client_id})") from err


def create_oauth_access_token_for_user(
    user,
    team_id: int,
    *,
    scopes: PosthogMcpScopes = "read_only",
    include_internal_scopes: bool = True,
) -> str:
    resolved = resolve_scopes(scopes, include_internal_scopes=include_internal_scopes)
    app = get_array_app()
    token_value = generate_random_oauth_access_token(None)

    OAuthAccessToken.objects.create(
        user=user,
        application=app,
        token=token_value,
        expires=timezone.now() + timedelta(seconds=TOKEN_EXPIRATION_SECONDS),
        scope=" ".join(resolved),
        scoped_teams=[team_id],
    )

    return token_value


def create_internal_oauth_access_token(scopes: list[str]) -> str:
    """Mint a user-less OAuth token for INTERNAL endpoints that reject
    team-scoped tokens (e.g. `/api/query_performance_proxy/`). Authenticated
    by `OAuthAccessTokenAuthentication` as a synthetic `InternalAPIUser`.

    Shape-wise this is an OAuth 2.0 client_credentials token (RFC 6749 §4.4):
    no user binding, scoped, time-bounded, individually revocable. PostHog's
    OAuth provider does not expose the `client_credentials` grant via the
    standard `/oauth/token` endpoint today (only `authorization_code` +
    `refresh_token` are advertised in OIDC metadata), so we mint the row
    directly via the ORM rather than going through the grant flow.

    The trade-off vs. plumbing client_credentials through the OAuth provider:
    we skip OIDC metadata changes, an `OAuthValidator` audit for the no-user
    path, a new `OAuthApplication` registration, and the token-endpoint route
    work — at the cost of procedural conformance to RFC 6749 §4.4. Security
    properties are unchanged (same `OAuthAccessToken` row, same auth backend,
    same scope/expiry/revocation surface), and the only minter is internal
    Django code with DB access. If a second internal service wants this
    pattern, that's the prompt to land real client_credentials support."""
    app = get_array_app()
    token_value = generate_random_oauth_access_token(None)

    OAuthAccessToken.objects.create(
        user=None,
        application=app,
        token=token_value,
        expires=timezone.now() + timedelta(seconds=TOKEN_EXPIRATION_SECONDS),
        scope=" ".join(scopes),
        scoped_teams=None,
    )

    return token_value
