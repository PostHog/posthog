"""The org-wide MCP read-only policy.

`Organization.mcp_access_read_only` caps what any member can do through the PostHog MCP
server. Reads work. Writes are denied. The cap applies to every member, including admins.
Access through the app and direct API use are not affected.

The class `MCPAccessPermission` in presentation/permissions.py is the first consumer. The
access-control facade's `decide()` can read this module later, to apply the same cap to
object-level decisions.
"""

from typing import Any, Protocol

from posthog.auth import OAuthAccessTokenAuthentication, PersonalAPIKeyAuthentication
from posthog.constants import AvailableFeature
from posthog.models.organization import Organization

# services/mcp sends this user agent on its API calls (USER_AGENT in its
# oauth-constants.ts). Keep the two in sync. A client controls its own user agent, so
# this match applies the policy to the normal MCP pathway only. It does not stop a
# hostile key holder. The same credential keeps its full scopes under a different user
# agent. A future change can reduce the credential's scopes when the token is created.
MCP_USER_AGENT_MARKER = "posthog/mcp-server"


class RequestLike(Protocol):
    """This protocol lists the request attributes this module reads. It is structural
    because the import-linter contract bans direct DRF imports from facade modules.
    Indirect DRF use (posthog.auth) is allowed by the same contract."""

    headers: Any


def is_mcp_request(request: RequestLike) -> bool:
    """Returns True when a token-authenticated request comes through the MCP server."""
    authenticator = getattr(request, "successful_authenticator", None)
    if isinstance(authenticator, PersonalAPIKeyAuthentication | OAuthAccessTokenAuthentication):
        return MCP_USER_AGENT_MARKER in (request.headers.get("User-Agent") or "")
    return False


def mcp_access_denial_for_request(request: RequestLike, organization: Organization, writes: bool) -> str | None:
    """Makes the MCP read-only decision for one request. Returns a denial message for the
    user when the organization restricts MCP access and the action writes. Returns None
    to allow the request."""
    if not writes:
        return None
    if not is_mcp_request(request):
        return None
    if not organization.mcp_access_read_only:
        return None
    if not organization.is_feature_available(AvailableFeature.ORGANIZATION_SECURITY_SETTINGS):
        return None
    return (
        "Your organization restricts MCP access to read-only. "
        "An organization admin can change this in your organization settings."
    )
