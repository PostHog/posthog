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
    "notebook:read",
    "organization:read",
    "tracing:read",
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
    "notebook:write",
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
