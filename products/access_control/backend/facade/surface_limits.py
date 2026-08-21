"""Per-surface access limits: org-wide caps on what any principal can do through one access
surface (the MCP server today; personal API keys, share links and impersonation later).

The first consumer is `WithinSurfaceLimits` in facade/permissions.py, which denies write-scoped
actions when the request's surface is limited below editor. When the access-control facade's `decide()` lands, it composes the same limit into
object-level decisions; both read this module, so enforcement points cannot disagree about what
the organization configured.
"""

from typing import TYPE_CHECKING, Any

from posthog.auth import OAuthAccessTokenAuthentication, PersonalAPIKeyAuthentication
from posthog.constants import AvailableFeature

from products.access_control.backend.models.surface_access_limit import SurfaceAccessLimit

if TYPE_CHECKING:
    from posthog.models.organization import Organization

# The outbound identity of services/mcp (see its oauth-constants.ts). Surface classification is
# governance of the pathway, not a defense against a hostile key holder: the same credential used
# outside MCP keeps its own scopes, and tightening the credential itself is the mint-time follow-up.
MCP_USER_AGENT_MARKER = "posthog/mcp-server"

WRITE_LIMITED_LEVELS = {SurfaceAccessLimit.MaxLevel.NONE, SurfaceAccessLimit.MaxLevel.VIEWER}


def classify_surface(request: Any) -> str | None:
    """The access surface this request arrived through, or None for surfaces without policies."""
    authenticator = getattr(request, "successful_authenticator", None)
    if isinstance(authenticator, PersonalAPIKeyAuthentication | OAuthAccessTokenAuthentication):
        user_agent = request.headers.get("User-Agent") or ""
        if MCP_USER_AGENT_MARKER in user_agent:
            return SurfaceAccessLimit.Surface.MCP
    return None


def limit_denial_for_request(
    request: Any, organization: "Organization", resource: str | None, writes: bool
) -> str | None:
    """The complete surface-limit decision: a user-facing denial message when this request's
    surface is limited below what the action needs, or None to allow.

    Owns classification, the entitlement gate, row lookup and the copy, so enforcement points
    (today `WithinSurfaceLimits`, later the facade's `decide()`) contain no policy of their own."""
    if not writes:
        return None
    surface = classify_surface(request)
    if surface is None:
        return None
    if not organization.is_feature_available(AvailableFeature.ORGANIZATION_SECURITY_SETTINGS):
        return None
    limit = surface_limit(organization, surface, resource)
    if limit in WRITE_LIMITED_LEVELS:
        return (
            "Your organization restricts MCP access to read-only. "
            "An organization admin can change this in your organization settings."
        )
    return None


def surface_limit(
    organization: "Organization", surface: str | None, resource: str | None = None
) -> SurfaceAccessLimit.MaxLevel | None:
    """The max level this organization allows through `surface`, or None when unrestricted.

    A row naming `resource` overrides the wildcard row. One query per call; callers on hot
    paths should classify the surface first, since surface=None short-circuits.
    """
    if surface is None:
        return None
    rows = SurfaceAccessLimit.objects.filter(
        organization=organization, surface=surface, resource__in=[resource, None] if resource else [None]
    ).values_list("resource", "max_level")
    by_resource = dict(rows)
    if resource is not None and resource in by_resource:
        return SurfaceAccessLimit.MaxLevel(by_resource[resource])
    if None in by_resource:
        return SurfaceAccessLimit.MaxLevel(by_resource[None])
    return None
