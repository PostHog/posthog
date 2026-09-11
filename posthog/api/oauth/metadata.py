"""Discovery documents for the OAuth authorization server.

Both documents describe one server, and a client reads whichever one its stack supports,
so they are built here rather than separately.
"""

from collections.abc import Mapping, Sequence

from posthog.api import id_jag
from posthog.api.oauth.claims import OIDC_CLAIMS
from posthog.dataclasses import frozen
from posthog.models.oauth import TokenEndpointAuthMethod
from posthog.scopes import get_oauth_scopes_supported, get_scope_descriptions

# What a discovery document holds: JSON, nested to whatever depth the field needs. The containers
# are covariant so a field can hold a concrete `list[str]`.
type JsonValue = str | bool | int | None | Sequence["JsonValue"] | Mapping[str, "JsonValue"]
type Document = dict[str, JsonValue]

SUPPORTED_GRANT_TYPES = [
    "authorization_code",
    "refresh_token",
    id_jag.JWT_BEARER_GRANT_TYPE,
]

# Every method a client can register under must appear here, or a client reads this
# document, picks a method we do not accept, and fails the token exchange.
SUPPORTED_TOKEN_ENDPOINT_AUTH_METHODS = [
    TokenEndpointAuthMethod.NONE.value,
    TokenEndpointAuthMethod.CLIENT_SECRET_POST.value,
    TokenEndpointAuthMethod.PRIVATE_KEY_JWT.value,
]

SERVICE_DOCUMENTATION = "https://posthog.com/docs/api"


def _shared_metadata(base_url: str) -> Document:
    return {
        "issuer": base_url,
        "authorization_endpoint": f"{base_url}/oauth/authorize/",
        "token_endpoint": f"{base_url}/oauth/token/",
        "userinfo_endpoint": f"{base_url}/oauth/userinfo/",
        "revocation_endpoint": f"{base_url}/oauth/revoke/",
        "introspection_endpoint": f"{base_url}/oauth/introspect/",
        "registration_endpoint": f"{base_url}/oauth/register/",
        "jwks_uri": f"{base_url}/.well-known/jwks.json",
        # Excludes the scopes an OAuth client cannot obtain self-serve, including `*`.
        "scopes_supported": get_oauth_scopes_supported(),
        # Only the authorization code flow is implemented.
        "response_types_supported": ["code"],
        "response_modes_supported": ["query"],
        "grant_types_supported": SUPPORTED_GRANT_TYPES,
        "token_endpoint_auth_methods_supported": SUPPORTED_TOKEN_ENDPOINT_AUTH_METHODS,
        # The `enforce_supported_code_challenge_method` constraint rejects `plain`.
        "code_challenge_methods_supported": ["S256"],
        "service_documentation": SERVICE_DOCUMENTATION,
    }


def openid_provider_metadata(base_url: str) -> Document:
    """OpenID Provider Metadata (OpenID Connect Discovery 1.0)."""
    return {
        **_shared_metadata(base_url),
        "subject_types_supported": ["public"],
        # The `enforce_rs256_algorithm` constraint on `OAuthApplication` rules out HS256.
        "id_token_signing_alg_values_supported": ["RS256"],
        "claims_supported": sorted(OIDC_CLAIMS),
    }


def authorization_server_metadata(base_url: str, region_info: Document | None = None) -> Document:
    """OAuth 2.0 Authorization Server Metadata (RFC 8414)."""
    return {
        **_shared_metadata(base_url),
        "authorization_grant_profiles_supported": [id_jag.ID_JAG_GRANT_PROFILE],
        # Client ID Metadata Document (draft-ietf-oauth-client-id-metadata-document-00)
        "client_id_metadata_document_supported": True,
        # auth.md agent registration profile (https://workos.com/auth-md).
        # Only flows that actually exist are advertised: ID-JAG identity
        # assertions at the identity endpoint. The user-claimed device flow
        # (claim_endpoint) and revocation receiver (events_endpoint) are not
        # built yet, so they are deliberately omitted rather than advertised.
        "agent_auth": {
            "skill": f"{base_url}/auth.md",
            "identity_endpoint": f"{base_url}/oauth/token/",
            "identity_types_supported": ["identity_assertion"],
            "identity_assertion": {
                "assertion_types_supported": ["urn:ietf:params:oauth:token-type:id-jag"],
            },
        },
        **(region_info or {}),
    }


def protected_resource_metadata(base_url: str) -> Document:
    """OAuth 2.0 Protected Resource Metadata (RFC 9728).

    Reached through the `WWW-Authenticate: Bearer resource_metadata=...` header on 401
    responses (see posthog/exceptions.py).
    """
    return {
        # Required by RFC 9728
        "resource": base_url,
        # The same PostHog instance is its own authorization server
        "authorization_servers": [base_url],
        "scopes_supported": get_oauth_scopes_supported(),
        "bearer_methods_supported": ["header"],
        "resource_documentation": SERVICE_DOCUMENTATION,
    }


# Identity and token-management scopes have no entry in get_scope_descriptions(),
# which only covers obj:action scopes. Every bare scope in
# `get_oauth_scopes_supported()` needs a line here, or the manifest prints the
# scope name where its description belongs.
_IDENTITY_SCOPE_DESCRIPTIONS = {
    "openid": "Sign in and read your user identifier",
    "profile": "Read your basic profile",
    "email": "Read your email address",
    "introspection": "Check whether a token you hold is still valid",
}


@frozen
class ManifestScope:
    """One advertised scope as the auth.md manifest lists it."""

    name: str
    description: str


def client_manifest_scopes() -> list[ManifestScope]:
    descriptions = get_scope_descriptions()
    return [
        ManifestScope(
            name=scope,
            description=descriptions[scope]
            if scope in descriptions
            else _IDENTITY_SCOPE_DESCRIPTIONS.get(scope, scope),
        )
        for scope in get_oauth_scopes_supported()
    ]
