"""
ID-JAG (XAA) implementation. See https://xaa.dev for more information.

TLDR: ID-JAG is a protocol where IdP's issue JWT tokens to their users
which they can send to us to issue a short-lived JWT token which can be
used to access our API. This eliminates the need for the user to oauth
to us, or get a personal API token to programmatically access our API.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, TypedDict, cast

from django.conf import settings
from django.core.cache import cache

import jwt
import requests
import structlog
from oauth2_provider.utils import jwk_from_pem
from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models.organization_domain import OrganizationDomain
from posthog.models.user import User
from posthog.scopes import get_oauth_scopes_supported
from posthog.security.url_validation import is_url_allowed

logger = structlog.get_logger(__name__)

# https://xaa.dev/docs/token-structure#id-jag — IdP issues ID-JAGs with this header `typ`.
ID_JAG_TOKEN_TYPE = "oauth-id-jag+jwt"

# https://xaa.dev/docs/token-structure#access-token — RFC 9068 access-token `typ`.
ACCESS_TOKEN_TYPE = "at+jwt"

# RFC 7521/7523 — JWT Bearer grant type identifier.
JWT_BEARER_GRANT_TYPE = "urn:ietf:params:oauth:grant-type:jwt-bearer"

# draft-ietf-oauth-identity-assertion-authz-grant §7.2 — advertised in metadata for ID-JAG discovery.
ID_JAG_GRANT_PROFILE = "urn:ietf:params:oauth:grant-profile:id-jag"


GENERIC_ID_JAG_REJECTION = "ID-JAG could not be verified"


class IdJagError(Exception):
    """
    OAuth-style token-endpoint error. The HTTP body shape follows RFC 6749
    section 5.2 and the XAA error-code table at
    https://xaa.dev/docs/error-codes
    """

    http_status: int = status.HTTP_400_BAD_REQUEST
    error_code: str = "invalid_request"

    def __init__(self, description: str, *, error_code: str | None = None, http_status: int | None = None) -> None:
        super().__init__(description)
        self.description = description
        if error_code is not None:
            self.error_code = error_code
        if http_status is not None:
            self.http_status = http_status


class InvalidRequestError(IdJagError):
    error_code = "invalid_request"


class InvalidGrantError(IdJagError):
    error_code = "invalid_grant"


class InvalidClientError(IdJagError):
    error_code = "invalid_client"
    http_status = status.HTTP_401_UNAUTHORIZED


class UnsupportedGrantTypeError(IdJagError):
    error_code = "unsupported_grant_type"


class InvalidScopeError(IdJagError):
    error_code = "invalid_scope"


class InvalidTargetError(IdJagError):
    # XAA error-code table lists `invalid_target` for resource-connection mismatch.
    # https://xaa.dev/docs/error-codes#idp-token-exchange
    error_code = "invalid_target"


class AccessDeniedError(IdJagError):
    # Special error for cases when the organization is not entitled to the XAA billing feature.
    # This is different from the generic `InvalidGrantError` which is used for cases when the ID-JAG is invalid.
    error_code = "access_denied"
    http_status = status.HTTP_403_FORBIDDEN


class IdJagClaims(TypedDict, total=False):
    iss: str
    sub: str
    email: str | None
    email_verified: bool
    aud: str | list[str]
    client_id: str
    scope: str
    resource: str
    jti: str
    iat: int
    nbf: int
    exp: int


def _get_site_url() -> str:
    """The deployment's public URL — used as `aud` for inbound ID-JAGs and as
    `iss`/`aud` for the access tokens we mint. Stripped of trailing slash so
    audience equality checks don't fight URL normalization."""
    site_url = (settings.SITE_URL or "").rstrip("/")
    if not site_url:
        raise InvalidGrantError(
            "ID-JAG authentication is not configured: SITE_URL is empty",
            http_status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_code="server_error",
        )
    return site_url


def _id_jag_allowlist(extra: list[str] | None) -> list[str]:
    """SITE_URL plus the trailing-slash-normalized `extra` values."""
    return [_get_site_url(), *[v.rstrip("/") for v in (extra or []) if v]]


def _get_allowed_audiences() -> list[str]:
    """Accepted ID-JAG `aud` values — the authorization-server issuer the client discovered.
    Always includes SITE_URL; Cloud adds the OAuth proxy via ID_JAG_ALLOWED_AUDIENCES."""
    return _id_jag_allowlist(settings.ID_JAG_ALLOWED_AUDIENCES)


def get_allowed_resources() -> list[str]:
    """Accepted ID-JAG `resource` values — the resource identifier the client discovered.
    Always includes SITE_URL; Cloud adds extra resource servers via ID_JAG_ALLOWED_RESOURCES.
    Also used by the resource server (posthog.auth) to validate the minted token's `aud`."""
    return _id_jag_allowlist(settings.ID_JAG_ALLOWED_RESOURCES)


def _get_jwks_client(issuer: str, jwks_url: str | None = None) -> jwt.PyJWKClient:
    """Resolve a `PyJWKClient` for the given IdP issuer.

    If `jwks_url` is provided (from the linked `IdentityProviderConfig.id_jag_jwks_url`),
    skip OIDC discovery and point PyJWKClient at it directly. Otherwise
    do OIDC discovery against `<issuer>/.well-known/openid-configuration` and
    cache the resulting `jwks_uri` for `ID_JAG_JWKS_CACHE_TTL_SECONDS`. We
    don't cache the `PyJWKClient` object itself because it already does
    in-process key caching (`lifespan` seconds) — caching only the URI keeps
    key rotation responsive while avoiding redundant discovery hits.

    Network and parse failures during discovery are normalized to
    `InvalidGrantError` so callers only have to handle one error type.
    """

    def _check_url(url: str, label: str) -> None:
        # SSRF guard
        allowed, reason = is_url_allowed(url)
        if not allowed:
            raise InvalidGrantError(f"IdP {label} URL is not allowed: {reason}")

    if jwks_url:
        _check_url(jwks_url, "JWKS")
        return jwt.PyJWKClient(jwks_url, timeout=10)

    _check_url(issuer, "issuer")
    cache_key = f"id_jag:jwks_uri:{issuer}"
    jwks_uri = cache.get(cache_key)
    if not jwks_uri:
        try:
            resp = requests.get(f"{issuer}/.well-known/openid-configuration", timeout=10, allow_redirects=False)
            resp.raise_for_status()
            metadata = resp.json()
        except requests.RequestException as e:
            raise InvalidGrantError(f"IdP {issuer} OIDC discovery request failed: {e}")
        except ValueError as e:
            # `resp.json()` raises `json.JSONDecodeError` (a ValueError subclass).
            raise InvalidGrantError(f"IdP {issuer} OIDC discovery response was not valid JSON: {e}")
        jwks_uri = metadata.get("jwks_uri")
        if not jwks_uri:
            raise InvalidGrantError(f"IdP {issuer} discovery metadata missing jwks_uri")
        cache.set(cache_key, jwks_uri, settings.ID_JAG_JWKS_CACHE_TTL_SECONDS)

    _check_url(jwks_uri, "discovered JWKS")
    return jwt.PyJWKClient(jwks_uri, timeout=10)


def _get_sub(provider_name: str, id_jag_sub: str) -> str:
    """
    Returns the `sub` claim in the expected ID-JAG format.

    {identity provider name}:{sub from ID-JAG token}

    Note: The ID-JAG token is the JWT issued by the identity provider which is passed
    in the API request to our django backend to issue a JWT access token to the caller.

    https://xaa.dev/docs/token-structure#sub-claim-format
    """
    return f"{provider_name}:{id_jag_sub}"


def _get_scopes(id_jag_scopes: list[str], requested_scopes: list[str] | None) -> list[str]:
    """
    Basically just takes the intersection of scopes requested in the caller
    and the scopers granted by the IdP in the ID-JAG token.

    https://xaa.dev/docs/token-structure#scope-intersection-rule

    Per spec, the intersection MAY be empty — the AS still issues a token, which
    then fails at the resource server with `403 insufficient_scope`. We mirror
    that behavior so clients see the documented failure mode, not a 400 here.

    `requested_scopes=None` means the client didn't pass a `scope` param, in
    which case the issued scope is exactly what the ID-JAG authorized. When
    `requested_scopes` is given, the result follows its order so deterministic
    output is stable across calls.
    """
    if requested_scopes is None:
        return list(id_jag_scopes)
    id_jag_set = set(id_jag_scopes)
    seen: set[str] = set()
    intersected: list[str] = []
    for scope in requested_scopes:
        if scope in id_jag_set and scope not in seen:
            seen.add(scope)
            intersected.append(scope)
    return intersected


def _verify_and_extract_id_jag_token(assertion: str) -> tuple[IdJagClaims, str, "OrganizationDomain"]:
    """
    Verifies the provided ID-JAG token against the IdP's JWKS and returns the
    claims, the provider name we stamp into the issued access token's `sub`,
    and the `OrganizationDomain` row that owns the trusted IdP config (used to
    bind the issued access token to a single organization).

    Raises `IdJagError` (with the right RFC 6749 error code) on every documented
    failure mode at https://xaa.dev/docs/error-codes
    """
    try:
        header = jwt.get_unverified_header(assertion)
    except jwt.PyJWTError as e:
        raise InvalidGrantError(f"ID-JAG header could not be parsed: {e}")

    if header.get("typ") != ID_JAG_TOKEN_TYPE:
        raise InvalidGrantError(f"ID-JAG typ header is not {ID_JAG_TOKEN_TYPE}")

    try:
        # Intentional: we need `iss` (and `email`/`sub`) to discover which IdP's
        # JWKS to fetch before we can verify the signature — the standard OIDC
        # bootstrap pattern. The verified `jwt.decode(...)` below is the
        # authoritative pass; nothing from `unverified_claims` is trusted past
        # the IdP-config lookup, and the verified pass re-reads every claim we
        # actually act on.
        # nosemgrep: python.jwt.security.unverified-jwt-decode.unverified-jwt-decode
        unverified_claims = jwt.decode(assertion, options={"verify_signature": False})
    except jwt.PyJWTError as e:
        raise InvalidGrantError(f"ID-JAG payload could not be parsed: {e}")

    issuer = (unverified_claims.get("iss") or "").rstrip("/")
    if not issuer:
        raise InvalidGrantError("ID-JAG is missing the iss claim")

    id_jag_email = unverified_claims.get("email") or unverified_claims.get("sub") or ""

    org_domain, error = OrganizationDomain.objects.get_verified_for_email_address_and_issuer(id_jag_email, issuer)
    if org_domain is None or error:
        # Do not echo the specific reason — see GENERIC_ID_JAG_REJECTION.
        logger.info(
            "id_jag_token_rejected",
            reason=error or "ID-JAG configuration is invalid",
            issuer=issuer,
            stage="pre_signature_domain_lookup",
        )
        raise InvalidGrantError(GENERIC_ID_JAG_REJECTION)

    idp_config = org_domain.idp_config
    expected_issuer = (idp_config.id_jag_issuer_url or "").rstrip("/")
    provider_name = org_domain.domain

    try:
        jwks_client = _get_jwks_client(expected_issuer, jwks_url=idp_config.id_jag_jwks_url or None)
        signing_key = jwks_client.get_signing_key_from_jwt(assertion)
    except jwt.PyJWTError as e:
        raise InvalidGrantError(f"ID-JAG signing key resolution failed: {e}")

    allowed_audiences = _get_allowed_audiences()

    try:
        claims = cast(
            IdJagClaims,
            jwt.decode(
                assertion,
                signing_key.key,
                algorithms=["RS256", "RS384", "RS512"],
                audience=allowed_audiences,
                leeway=settings.ID_JAG_CLOCK_SKEW_SECONDS,
                options={
                    "require": ["iss", "sub", "aud", "exp", "iat", "client_id"],
                    "verify_signature": True,
                    "verify_exp": True,
                    "verify_nbf": True,
                    "verify_iat": True,
                    "verify_aud": True,
                    # We verify `iss` manually below so the comparison is
                    # trailing-slash-tolerant — PyJWT's built-in check is
                    # strict string equality.
                    "verify_iss": False,
                },
            ),
        )
    except jwt.ExpiredSignatureError:
        raise InvalidGrantError("ID-JAG has expired")
    except jwt.ImmatureSignatureError as e:
        # PyJWT raises this for both `nbf > now+leeway` and `iat > now+leeway`,
        # and the message disambiguates between them.
        # https://xaa.dev/docs/token-structure#clock-skew-tolerance
        raise InvalidGrantError(f"ID-JAG is not yet valid (clock-skew window exceeded): {e}")
    except jwt.InvalidAudienceError:
        raise InvalidGrantError("ID-JAG aud doesn't match this Auth Server's URL")
    except jwt.MissingRequiredClaimError as e:
        raise InvalidGrantError(f"ID-JAG is missing required claim: {e.claim}")
    except jwt.PyJWTError as e:
        raise InvalidGrantError(f"ID-JAG signature verification failed: {e}")

    claim_issuer = (claims.get("iss") or "").rstrip("/")
    if claim_issuer != expected_issuer:
        # Mirror the pre-signature path so the response surface is uniform.
        logger.info(
            "id_jag_token_rejected",
            reason="ID-JAG iss does not match the IdP configured for this email's domain",
            claim_issuer=claim_issuer,
            expected_issuer=expected_issuer,
            stage="post_signature_iss_check",
        )
        raise InvalidGrantError(GENERIC_ID_JAG_REJECTION)

    resource = claims.get("resource")
    if not resource:
        raise InvalidGrantError("ID-JAG is missing the resource claim (RFC 8707)")
    resource = resource.rstrip("/")
    if resource not in get_allowed_resources():
        raise InvalidTargetError(f"ID-JAG resource {resource!r} does not match this resource server")
    # Store the normalized value back so the minted token's `aud` is consistent.
    claims["resource"] = resource

    client_id = claims.get("client_id")
    if not client_id:
        raise InvalidGrantError("ID-JAG is missing the client_id claim")

    # validate allowed clients if set in config
    if idp_config.id_jag_allowed_clients and client_id not in idp_config.id_jag_allowed_clients:
        raise InvalidClientError(f"client_id {client_id!r} is not allowed for this domain")

    # prevent replayed tokens from being used again
    jti = claims.get("jti")
    if jti:
        cache_key = f"id_jag:jti:{expected_issuer}:{jti}"
        exp = int(claims.get("exp") or 0)
        now = int(datetime.now(tz=UTC).timestamp())
        ttl = max(1, exp - now + settings.ID_JAG_CLOCK_SKEW_SECONDS)
        # `cache.add` is SETNX semantics: returns True only if the key was
        # newly created. A False return means we've already seen this jti.
        if not cache.add(cache_key, "1", ttl):
            raise InvalidGrantError("ID-JAG assertion has already been used (jti replay)")
    else:
        logger.info("id_jag_assertion_missing_jti", issuer=expected_issuer)

    # Some IdPs let a user set an arbitrary `email` with `email_verified: false`
    if claims.get("email") is not None and claims.get("email_verified") is False:
        logger.info(
            "id_jag_token_rejected",
            reason="email_not_verified",
            issuer=expected_issuer,
            stage="post_signature_email_verified_check",
        )
        raise InvalidGrantError(GENERIC_ID_JAG_REJECTION)

    verified_email = claims.get("email") or claims.get("sub") or ""

    # The user must be an active member of the *specific* organization whose
    # OrganizationDomain pinned this IdP — not merely a member of any org that
    # also verified this domain. The issued access token is scoped to
    # `org_domain.organization_id` downstream, so membership must be enforced
    # on that exact org.
    is_member = User.objects.filter(
        is_active=True,
        email__iexact=verified_email,
        organization_membership__organization_id=org_domain.organization.pk,
    ).exists()
    if not is_member:
        raise InvalidGrantError(
            "ID-JAG sub is not an active member of the organization that owns this IdP configuration"
        )

    return claims, provider_name, org_domain


def _construct_access_token_payload(
    claims: IdJagClaims,
    provider_name: str,
    granted_scopes: list[str],
    organization_id: Any,
    verified_email: str,
) -> dict[str, Any]:
    """
    Constructs the payload for the JWT access token which will be issued to the ID-JAG caller.

    https://xaa.dev/docs/token-structure#access-token
    """

    now = datetime.now(tz=UTC)
    expires_at = now + timedelta(seconds=settings.ID_JAG_ACCESS_TOKEN_TTL_SECONDS)

    payload: dict[str, Any] = {
        "iss": _get_site_url(),
        "sub": _get_sub(provider_name, cast(str, claims.get("sub"))),
        "email": verified_email,
        "aud": claims.get("resource"),
        "client_id": claims.get("client_id"),
        "scope": " ".join(granted_scopes),
        "app_org": provider_name,
        "org_id": str(organization_id),
        "jti": str(uuid.uuid4()),
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    return payload


def _get_signing_key() -> str:
    """RS256 private key used to sign access tokens. Reuses the OIDC key already
    deployed for OAuth so resource servers can verify access tokens against the
    existing `/.well-known/jwks.json` endpoint without extra wiring."""
    key = getattr(settings, "OIDC_RSA_PRIVATE_KEY", None)
    if not key:
        raise InvalidGrantError(
            "ID-JAG access tokens cannot be signed: OIDC_RSA_PRIVATE_KEY is not configured",
            http_status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_code="server_error",
        )
    return key


def _construct_access_token(payload: dict[str, Any]) -> str:
    signing_key = _get_signing_key()
    # `kid` matches the thumbprint published in `/.well-known/jwks.json`, so a
    # resource server can pick the right key once a rotation publishes more than one.
    return jwt.encode(
        payload,
        signing_key,
        algorithm="RS256",
        headers={"typ": ACCESS_TOKEN_TYPE, "kid": jwk_from_pem(signing_key).thumbprint()},
    )


def _parse_scope_list(value: str | list[str] | None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [s for s in value if s]
    return [s for s in value.split() if s]


def issue_access_token(
    assertion: str, requested_scope: str | list[str] | None, request_client_id: str | None
) -> tuple[str, list[str], int]:
    """
    Validate an ID-JAG `assertion` and mint an access token. Pulled out of the
    view so the same path is exercised by tests, batch tools, and the HTTP
    handler. Returns `(access_token, granted_scopes, expires_in_seconds)`.
    """

    claims, provider_name, org_domain = _verify_and_extract_id_jag_token(assertion)

    organization = org_domain.organization
    if not organization.is_feature_available(AvailableFeature.XAA_AUTHENTICATION):
        raise AccessDeniedError("ID-JAG (XAA) is not enabled for this organization")

    if request_client_id and request_client_id != claims.get("client_id"):
        raise InvalidGrantError("ID-JAG client_id doesn't match the authenticating client")

    id_jag_scopes = _parse_scope_list(claims.get("scope"))
    parsed_requested = _parse_scope_list(requested_scope) if requested_scope is not None else None

    known_scopes = set(get_oauth_scopes_supported())
    sanitized_id_jag_scopes = [s for s in id_jag_scopes if s in known_scopes]

    granted = _get_scopes(sanitized_id_jag_scopes, parsed_requested)
    verified_email = claims.get("email") or claims.get("sub") or ""
    payload = _construct_access_token_payload(
        claims, provider_name, granted, organization.pk, cast(str, verified_email)
    )
    token = _construct_access_token(payload)
    return token, granted, settings.ID_JAG_ACCESS_TOKEN_TTL_SECONDS
