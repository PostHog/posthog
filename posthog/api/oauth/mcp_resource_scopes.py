from __future__ import annotations

from typing import TypedDict
from urllib.parse import urlparse

import requests
import structlog

from posthog.cloud_utils import is_dev_mode
from posthog.scopes import get_oauth_scopes_supported

logger = structlog.get_logger(__name__)

METADATA_TIMEOUT_SECONDS = 5
WELL_KNOWN_PREFIX = "/.well-known/oauth-protected-resource"

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
    scopes_fetch_failed: bool


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


def _protected_resource_metadata_url(resource_url: str) -> str:
    parsed = urlparse(resource_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    resource_path = parsed.path if parsed.path not in {"", "/"} else ""
    return f"{origin}{WELL_KNOWN_PREFIX}{resource_path}"


def fetch_mcp_protected_resource_scopes(resource_url: str) -> list[str] | None:
    """Fetch scopes_supported for a trusted PostHog MCP resource URL.

    Returns None when metadata cannot be loaded. Caller should treat that as a
    fetch failure and fall back to the frontend's reduced scope list.
    """
    metadata_url = _protected_resource_metadata_url(resource_url)
    parsed = urlparse(resource_url)
    resource_path = parsed.path if parsed.path not in {"", "/"} else ""

    try:
        response = requests.get(metadata_url, timeout=METADATA_TIMEOUT_SECONDS)
        if response.status_code == 404 and resource_path:
            fallback_url = f"{parsed.scheme}://{parsed.netloc}{WELL_KNOWN_PREFIX}"
            response = requests.get(fallback_url, timeout=METADATA_TIMEOUT_SECONDS)
        if not response.ok:
            logger.warning(
                "mcp_resource_scopes_metadata_http_error",
                resource_url=resource_url,
                metadata_url=metadata_url,
                status_code=response.status_code,
            )
            return None

        metadata = response.json()
        scopes_supported = metadata.get("scopes_supported")
        if not isinstance(scopes_supported, list) or not all(isinstance(scope, str) for scope in scopes_supported):
            logger.warning(
                "mcp_resource_scopes_metadata_invalid",
                resource_url=resource_url,
                metadata_url=metadata_url,
            )
            return None

        known_scopes = set(get_oauth_scopes_supported())
        return [scope for scope in scopes_supported if scope in known_scopes]
    except (requests.RequestException, ValueError) as error:
        logger.warning(
            "mcp_resource_scopes_metadata_fetch_failed",
            resource_url=resource_url,
            metadata_url=metadata_url,
            error=str(error),
        )
        return None


def build_oauth_mcp_consent_context(resource_url: str | None) -> OAuthMcpConsentContext | None:
    if not resource_url or not is_trusted_posthog_mcp_resource(resource_url):
        return None

    scopes = fetch_mcp_protected_resource_scopes(resource_url)
    if scopes is None:
        return OAuthMcpConsentContext(is_mcp_resource=True, scopes_fetch_failed=True)

    return OAuthMcpConsentContext(is_mcp_resource=True, scopes=scopes, scopes_fetch_failed=False)
