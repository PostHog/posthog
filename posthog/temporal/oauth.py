from datetime import timedelta
from typing import Literal

from django.utils import timezone

from posthog.models import OAuthAccessToken, OAuthApplication
from posthog.models.utils import generate_random_oauth_access_token
from posthog.scopes import API_SCOPE_OBJECTS, INTERNAL_API_SCOPE_OBJECTS, OAUTH_HIDDEN_SCOPE_OBJECTS
from posthog.utils import get_instance_region

ARRAY_APP_CLIENT_ID_US = "HCWoE0aRFMYxIxFNTTwkOORn5LBjOt2GVDzwSw5W"
ARRAY_APP_CLIENT_ID_EU = "AIvijgMS0dxKEmr5z6odvRd8Pkh5vts3nPTzgzU9"
ARRAY_APP_CLIENT_ID_DEV = "DC5uRLVbGI02YQ82grxgnK6Qn12SXWpCqdPb60oZ"

McpScopePreset = Literal["read_only", "full"]


INTERNAL_SCOPES: list[str] = [
    "task:write",
    "llm_gateway:read",
]


# Derived from posthog.scopes so the token issued to a sandboxed agent cannot
# drift out of subset of what the MCP server advertises in
# `services/mcp/src/lib/oauth-scopes.generated.ts` (itself generated from
# `get_oauth_scopes_supported()` via `bin/build-mcp-oauth-scopes.py`). Scopes
# already covered by INTERNAL_SCOPES are excluded so resolve_scopes() doesn't
# emit duplicates.
def _build_mcp_scopes(action: Literal["read", "write"]) -> list[str]:
    excluded_objects = INTERNAL_API_SCOPE_OBJECTS | OAUTH_HIDDEN_SCOPE_OBJECTS
    internal_set = set(INTERNAL_SCOPES)
    return [
        f"{obj}:{action}"
        for obj in API_SCOPE_OBJECTS
        if obj not in excluded_objects and f"{obj}:{action}" not in internal_set
    ]


MCP_READ_SCOPES: list[str] = _build_mcp_scopes("read")
MCP_WRITE_SCOPES: list[str] = _build_mcp_scopes("write")

TOKEN_EXPIRATION_SECONDS = 60 * 60 * 6  # 6 hours

PosthogMcpScopes = McpScopePreset | list[str]

MCP_SCOPE_PRESETS = ("read_only", "full")


def resolve_scopes(scopes: PosthogMcpScopes = "read_only", *, include_internal_scopes: bool = True) -> list[str]:
    internal = list(INTERNAL_SCOPES) if include_internal_scopes else []
    if isinstance(scopes, str):
        if scopes == "full":
            resolved = [*MCP_READ_SCOPES, *MCP_WRITE_SCOPES, *internal]
        else:
            resolved = [*MCP_READ_SCOPES, *internal]
    else:
        resolved = [*scopes, *internal]
    return list(dict.fromkeys(resolved))


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
