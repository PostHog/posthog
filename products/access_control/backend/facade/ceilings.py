"""Per-channel access ceilings: org-wide caps on what any principal can do through one pathway.

The first consumer is `APIScopePermission`, which denies write-scoped actions when the request's
channel is capped below editor. When the access-control facade's `decide()` lands, it composes the
same cap into object-level decisions; both read this module, so the two enforcement points cannot
disagree about what the organization configured.
"""

from typing import TYPE_CHECKING, Any

from posthog.auth import OAuthAccessTokenAuthentication, PersonalAPIKeyAuthentication

from products.access_control.backend.models.access_ceiling import AccessCeiling

if TYPE_CHECKING:
    from posthog.models.organization import Organization

# The outbound identity of services/mcp (see its oauth-constants.ts). Channel classification is
# governance of the pathway, not a defense against a hostile key holder: the same credential used
# outside MCP keeps its own scopes, and tightening the credential itself is the mint-time follow-up.
MCP_USER_AGENT_MARKER = "posthog/mcp-server"

WRITE_CAPPED_LEVELS = {AccessCeiling.MaxLevel.NONE, AccessCeiling.MaxLevel.VIEWER}


def classify_channel(request: Any) -> str | None:
    """The access pathway this request arrived through, or None for pathways without policies."""
    authenticator = getattr(request, "successful_authenticator", None)
    if isinstance(authenticator, PersonalAPIKeyAuthentication | OAuthAccessTokenAuthentication):
        user_agent = request.headers.get("User-Agent") or ""
        if MCP_USER_AGENT_MARKER in user_agent:
            return AccessCeiling.Channel.MCP
    return None


def channel_ceiling(
    organization: "Organization", channel: str | None, resource: str | None = None
) -> AccessCeiling.MaxLevel | None:
    """The max level this organization allows through `channel`, or None when unrestricted.

    A row naming `resource` overrides the wildcard row. One query per call; callers on hot
    paths should check the channel first, since channel=None short-circuits.
    """
    if channel is None:
        return None
    rows = AccessCeiling.objects.filter(
        organization=organization, channel=channel, resource__in=[resource, None] if resource else [None]
    ).values_list("resource", "max_level")
    by_resource = dict(rows)
    if resource is not None and resource in by_resource:
        return AccessCeiling.MaxLevel(by_resource[resource])
    if None in by_resource:
        return AccessCeiling.MaxLevel(by_resource[None])
    return None
