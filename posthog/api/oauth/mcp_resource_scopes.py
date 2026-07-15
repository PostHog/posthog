from __future__ import annotations

import os
import json
from functools import lru_cache
from typing import TypedDict
from urllib.parse import urlparse

import structlog

from posthog.cloud_utils import is_dev_mode
from posthog.scopes import get_oauth_scopes_supported
from posthog.settings.base_variables import BASE_DIR

logger = structlog.get_logger(__name__)

# The MCP server builds its RFC 9728 `scopes_supported` from this same committed
# artifact (services/mcp/src/tools/toolDefinitions.ts reads it too). Deriving the
# consent list from it here keeps the authorization server's promise sourced from
# its own state instead of a runtime fetch to the resource server.
_TOOL_DEFINITIONS_PATH = os.path.join(BASE_DIR, "services", "mcp", "schema", "generated-tool-definitions.json")

# Keep in sync with services/mcp/src/lib/routing.ts regional MCP hostnames.
PRODUCTION_MCP_HOSTS = frozenset(
    {
        "mcp.posthog.com",
        "mcp.us.posthog.com",
        "mcp.eu.posthog.com",
        "mcp-eu.posthog.com",
    }
)
LOCAL_MCP_HOSTS = frozenset({"localhost", "127.0.0.1"})


class OAuthMcpConsentContext(TypedDict, total=False):
    is_mcp_resource: bool
    scopes: list[str]


def is_trusted_posthog_mcp_resource(resource_url: str) -> bool:
    try:
        parsed = urlparse(resource_url)
    except ValueError:
        return False

    if parsed.scheme not in {"https", "http"}:
        return False

    hostname = (parsed.hostname or "").lower()
    if hostname in PRODUCTION_MCP_HOSTS:
        return parsed.scheme == "https"

    if is_dev_mode() and hostname in LOCAL_MCP_HOSTS:
        return parsed.scheme == "http"

    return False


@lru_cache(maxsize=1)
def _tool_required_scopes() -> frozenset[str]:
    with open(_TOOL_DEFINITIONS_PATH) as definitions_file:
        definitions = json.load(definitions_file)

    return frozenset(
        scope for definition in definitions.values() for scope in (definition.get("required_scopes") or [])
    )


def mcp_advertised_scopes() -> list[str]:
    """The scopes an MCP client gets when it omits `scope` on `/oauth/authorize`.

    Mirrors the MCP server's `getAdvertisedOAuthScopes()`: every identity scope
    (no `:`) plus the resource scopes some tool actually requires, both drawn from
    the authorization server's own supported set so nothing advertised is later
    rejected at `/authorize`.
    """
    required = _tool_required_scopes()
    return [scope for scope in get_oauth_scopes_supported() if ":" not in scope or scope in required]


def build_oauth_mcp_consent_context(resource_url: str | None) -> OAuthMcpConsentContext | None:
    if not resource_url or not is_trusted_posthog_mcp_resource(resource_url):
        return None

    return OAuthMcpConsentContext(is_mcp_resource=True, scopes=mcp_advertised_scopes())
