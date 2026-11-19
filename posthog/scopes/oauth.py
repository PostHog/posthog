"""Which scopes each OAuth surface names: identity scopes and the discovery lists.

Each class of scope reaches a different set of OAuth surfaces. A scope string belongs to
exactly one class:

| Class                     | Defined by                         | OAuth grant                        | AS metadata | Other discovery |
| ------------------------- | ---------------------------------- | ---------------------------------- | ----------- | --------------- |
| Internal                  | `INTERNAL_API_SCOPE_OBJECTS`       | Never. Minted server-side only     | No          | No              |
| Hidden                    | `OAUTH_SCOPES_HIDDEN`              | Only on an admin-set app ceiling   | No          | No              |
| Privileged                | `PRIVILEGED_SCOPES`                | Only on an admin-set app ceiling   | No          | No              |
| Authorization server only | `AUTHORIZATION_SERVER_ONLY_SCOPES` | Only to staff-marked apps, alone   | Yes         | No              |
| Identity                  | `ALWAYS_ALLOWED_SCOPES`            | Always, whatever the app ceiling   | Yes         | Yes             |
| Resource                  | `UNPRIVILEGED_SCOPES`              | Within the app's ceiling           | Yes         | Yes             |

"AS metadata" is the RFC 8414 document at `/.well-known/oauth-authorization-server`, which
lists `AUTHORIZATION_SERVER_SCOPES_SUPPORTED`. "Other discovery" is every other place a client
reads scopes from, which all list `OAUTH_SCOPES_SUPPORTED`: the protected resource metadata
(Django and the MCP server), the OpenID discovery document and the auth.md manifest.

The internal, hidden, privileged and resource sets live in `exposure`. Hidden and privileged
scopes behave the same for OAuth but differ for personal API keys and the MCP server, as their
definitions say. Personal API keys and the scope pickers are separate surfaces:
`exposure.get_scope_descriptions()` and `exposure.EXPOSED_SCOPE_OBJECTS` decide what they offer.
"""

from . import catalog, exposure

# The OpenID Connect identity scopes. A plain tuple rather than an import from
# django-oauth-toolkit, so this module loads without Django, which
# `posthog/scopes_projection.py` needs.
OIDC_SCOPES: tuple[str, ...] = ("openid", "profile", "email")

# Identity: the OIDC scopes plus `introspection`. They describe the user or the token rather than
# a resource, so any token may carry them whatever its app's ceiling.
ALWAYS_ALLOWED_SCOPES: frozenset[str] = frozenset(OIDC_SCOPES) | {"introspection"}

EMA_ISSUER_MANAGE_SCOPE = "ema_issuer:manage"


def _build_oauth_scopes_supported() -> tuple[str, ...]:
    # `OIDC_SCOPES` keeps its declared order at the head of the list. The other identity scopes
    # and the resource scopes follow in a fixed order, so the generated MCP artifact stays
    # byte-stable.
    other_identity = sorted(ALWAYS_ALLOWED_SCOPES - set(OIDC_SCOPES))
    resource = [
        f"{obj}:{action}"
        for obj in catalog.API_SCOPE_OBJECTS
        for action in catalog.API_SCOPE_ACTIONS
        if f"{obj}:{action}" in exposure.UNPRIVILEGED_SCOPES
    ]
    return (*OIDC_SCOPES, *other_identity, *resource)


# Identity plus resource scopes: what any OAuth client may request, and the list every discovery
# document publishes. The identity scopes are listed although every token carries them, because a
# client warns the user when a scope it requested is missing here. An internal scope must never get
# in, or any client could ask a person to consent to it. For example, the scratchpad that
# `signal_scout_internal:write` writes is read into every later agent prompt.
OAUTH_SCOPES_SUPPORTED: tuple[str, ...] = _build_oauth_scopes_supported()

# Authorization server only: scopes for setup flows that only staff-marked apps can get
# (`ema_issuer:manage`). Clients look for them in the authorization server metadata before they
# offer the feature. They stay out of the protected resource metadata and `WWW-Authenticate`,
# because MCP clients request every scope listed there. `authorization_server_metadata()` has more.
AUTHORIZATION_SERVER_ONLY_SCOPES: tuple[str, ...] = (EMA_ISSUER_MANAGE_SCOPE,)

# The list the authorization server metadata publishes.
AUTHORIZATION_SERVER_SCOPES_SUPPORTED: tuple[str, ...] = (*OAUTH_SCOPES_SUPPORTED, *AUTHORIZATION_SERVER_ONLY_SCOPES)
