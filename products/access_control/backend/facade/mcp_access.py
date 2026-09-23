"""The org-wide MCP read-only policy.

`Organization.read_only_mcp_access` caps what any member can do through the PostHog MCP
server. Reads work. Writes are denied. The cap applies to every member, including admins.
Access through the app and direct API use are not affected.

This module is the decision point. It takes domain facts and returns a verdict. It does
not read requests. `posthog.auth.is_mcp_request` classifies the pathway. Enforcement
points such as `MCPAccessPermission` in posthog/permissions.py gather the facts and
apply the verdict. The access-control facade's `decide()` can call this later, to apply the
same cap to object-level decisions.
"""

from posthog.constants import AvailableFeature
from posthog.models.organization import Organization


def mcp_access_denial(organization: Organization, *, is_mcp: bool, writes: bool) -> str | None:
    """Makes the MCP read-only decision. Returns a denial message for the user when the
    organization restricts MCP access and the action writes. Returns None to allow."""
    if not writes or not is_mcp:
        return None
    if not organization.read_only_mcp_access:
        return None
    if not organization.is_feature_available(AvailableFeature.ORGANIZATION_SECURITY_SETTINGS):
        return None
    return (
        "Your organization restricts MCP access to read-only. "
        "An organization admin can change this in your organization settings."
    )
