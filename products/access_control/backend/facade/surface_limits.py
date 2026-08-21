"""Per-surface access limits.

An access surface is a path that requests use to reach PostHog. Examples: the MCP server,
a personal API key, a public share link, an impersonated session. A surface limit is an
organization-wide cap on what any principal can do through one surface. The MCP server is
the only surface with limits today.

The class `SurfaceAccessLimitPermission` in facade/permissions.py is the first consumer. It
denies actions that need more than the surface's limit allows. The
access-control facade's `decide()` will also read this module later, to apply the same
limit to object-level decisions. All enforcement points read one module, so they cannot
disagree about the configured limits.
"""

from typing import TYPE_CHECKING

from django.http import HttpRequest

from rest_framework.request import Request

from posthog.auth import OAuthAccessTokenAuthentication, PersonalAPIKeyAuthentication
from posthog.constants import AvailableFeature

from products.access_control.backend.models.surface_access_limit import SurfaceAccessLimit

if TYPE_CHECKING:
    from posthog.models.organization import Organization

# The outbound identity of services/mcp (see its oauth-constants.ts). Surface
# classification controls the pathway. It is not a defense against a hostile key holder.
# The same credential keeps its full scopes outside MCP. A future change can reduce the
# credential's scopes when the token is created.
MCP_USER_AGENT_MARKER = "posthog/mcp-server"


def classify_surface(request: HttpRequest | Request) -> str | None:
    """Returns the access surface of this request. Returns None for paths that have no
    surface policies."""
    authenticator = getattr(request, "successful_authenticator", None)
    if isinstance(authenticator, PersonalAPIKeyAuthentication | OAuthAccessTokenAuthentication):
        user_agent = request.headers.get("User-Agent") or ""
        if MCP_USER_AGENT_MARKER in user_agent:
            return SurfaceAccessLimit.Surface.MCP
    return None


def limit_denial_for_request(
    request: HttpRequest | Request, organization: "Organization", resource: str, writes: bool
) -> str | None:
    """Makes the full surface-limit decision for one request. Returns a denial message for
    the user when the organization limits the request's surface below what the action needs.
    Returns None to allow the request. A `"none"` limit denies reads and writes both.

    This function contains all the policy: surface classification, the feature-entitlement
    check, the row lookup, and the message text. Enforcement points (`SurfaceAccessLimitPermission`
    today, the facade's `decide()` later) apply the result and add no policy of their own."""
    surface = classify_surface(request)
    if surface is None:
        return None
    if not organization.is_feature_available(AvailableFeature.ORGANIZATION_SECURITY_SETTINGS):
        return None
    limit = surface_limit(organization, surface, resource)
    if limit == SurfaceAccessLimit.MaxLevel.NONE:
        return (
            "Your organization has disabled MCP access. "
            "An organization admin can change this in your organization settings."
        )
    if writes and limit == SurfaceAccessLimit.MaxLevel.VIEWER:
        return (
            "Your organization restricts MCP access to read-only. "
            "An organization admin can change this in your organization settings."
        )
    return None


def surface_limit(
    organization: "Organization", surface: str, resource: str = SurfaceAccessLimit.ALL_RESOURCES
) -> SurfaceAccessLimit.MaxLevel | None:
    """Returns the max level this organization allows through `surface`. Returns None when
    the surface has no limit.

    A row that names `resource` overrides the `"*"` wildcard row. Each call makes one query.
    """
    wildcard = SurfaceAccessLimit.ALL_RESOURCES
    rows = SurfaceAccessLimit.objects.filter(
        organization=organization, surface=surface, resource__in={resource, wildcard}
    ).values_list("resource", "max_level")
    by_resource = dict(rows)
    if resource in by_resource:
        return SurfaceAccessLimit.MaxLevel(by_resource[resource])
    if wildcard in by_resource:
        return SurfaceAccessLimit.MaxLevel(by_resource[wildcard])
    return None
