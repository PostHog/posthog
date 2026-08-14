"""``private_key_jwt`` client authentication (RFC 7521 / RFC 7523 section 2.2).

A client authenticates by signing a short-lived JWT with its private key instead of
presenting a shared secret. We verify the signature against the public keys the client
publishes at its ``jwks_uri``, so no credential ever has to be transmitted to us or stored
by us, and the client can rotate keys on its own by publishing a new set.

This pairs particularly well with CIMD clients, whose ``client_id`` is itself an HTTPS URL:
control of that URL is what establishes the client's identity, so a key served from it is
authentic without any registration ceremony.
"""

from __future__ import annotations

import time
from dataclasses import field
from typing import Any

from django.conf import settings
from django.core.cache import cache

import jwt
import structlog
from jwt import PyJWK, PyJWKSet

from posthog.api.oauth.cimd import CIMDFetchError, CIMDValidationError, fetch_client_json_document
from posthog.dataclasses import frozen
from posthog.models.oauth import OAuthApplication

logger = structlog.get_logger(__name__)


@frozen
class ResolvedClientAssertion:
    # repr=False: the assertion is a signed credential, kept out of logs and tracebacks.
    client_assertion: str = field(repr=False)
    client_id: str


CLIENT_ASSERTION_TYPE_JWT_BEARER = "urn:ietf:params:oauth:client-assertion-type:jwt-bearer"

# Asymmetric signatures only. Allowing an HMAC family here would be a key-confusion hole:
# the "public" key we fetch is attacker-publishable, so an HS256 assertion signed with that
# same value as the shared secret would verify. "none" is excluded for the same reason.
ALLOWED_ASSERTION_ALGORITHMS = ["RS256", "RS384", "RS512", "PS256", "PS384", "PS512", "ES256", "ES384", "ES512"]

# An assertion is a single-use credential presented immediately, so it needs no real
# lifetime. Capping it bounds how long a captured assertion is replayable if the jti cache
# is ever lost, and bounds how far ahead a client may pre-mint.
MAX_ASSERTION_LIFETIME_SECONDS = 300
ASSERTION_CLOCK_SKEW_SECONDS = 30

JWKS_CACHE_PREFIX = "oauth_client_jwks:"
JWKS_CACHE_TTL_SECONDS = 3600
# Short negative TTL so a client that has just fixed a broken JWKS isn't locked out for an
# hour, while a persistently broken one still can't trigger a fetch per request.
JWKS_NEGATIVE_CACHE_TTL_SECONDS = 60
# A rotated key legitimately shows up as unknown until the cached JWKS expires, so one
# forced re-fetch is allowed per interval. The bound keeps assertions naming bogus kids from
# turning every exchange into an outbound fetch.
JWKS_ROTATION_REFRESH_MIN_INTERVAL_SECONDS = 60
JWKS_MAX_DOCUMENT_SIZE = 16 * 1024
JWKS_MAX_KEYS = 10

JTI_CACHE_PREFIX = "oauth_client_assertion_jti:"


class ClientAssertionError(Exception):
    """The assertion is missing, malformed, or does not verify. The message is wire-safe."""


class UnknownSigningKeyError(ClientAssertionError):
    """The assertion names a ``kid`` that the client's cached key set does not contain."""


def _request_field(request: Any, name: str) -> str:
    """Read a field from the request body, falling back to the query string.

    RFC 7523 section 2.2 sends these as form parameters, which a GET has nowhere to put. The
    GitHub grant listing endpoint is a GET, so without the query-string fallback a
    private_key_jwt client could not authenticate there at all, while a client_secret one
    could (its credentials ride the Basic header). An assertion is single-use and capped at
    MAX_ASSERTION_LIFETIME_SECONDS, so one appearing in an access log is already spent.
    """
    from_body = request.data.get(name) if hasattr(request, "data") else None
    if from_body:
        return str(from_body)
    return str(request.query_params.get(name) or "") if hasattr(request, "query_params") else ""


def extract_client_assertion(request: Any) -> ResolvedClientAssertion | None:
    """Return the client assertion and client_id a request presents, or None.

    ``client_id`` is optional on the wire for this method (RFC 7521 section 4.2 allows the
    assertion to carry the identity), so it falls back to the assertion's own ``sub``.
    """
    return resolve_client_assertion(
        _request_field(request, "client_assertion"),
        _request_field(request, "client_assertion_type"),
        _request_field(request, "client_id"),
    )


def resolve_client_assertion(assertion: str, assertion_type: str, client_id: str) -> ResolvedClientAssertion | None:
    """Return the client assertion and client_id from raw field values, or None.

    Kept separate from ``extract_client_assertion`` so the oauthlib-backed token endpoint,
    whose request object exposes these fields as plain attributes rather than through the DRF
    ``request.data`` interface, can share the same resolution and ``sub`` fallback.
    """
    if not assertion or assertion_type != CLIENT_ASSERTION_TYPE_JWT_BEARER:
        return None

    resolved_client_id = client_id or _unverified_subject(assertion)
    if not resolved_client_id:
        return None

    return ResolvedClientAssertion(client_assertion=assertion, client_id=resolved_client_id)


def _unverified_subject(assertion: str) -> str:
    """Read ``sub`` without verifying, only to locate which client to verify against.

    Never trusted for authentication: the claim is re-checked against the resolved
    application's client_id after the signature verifies.
    """
    try:
        # nosemgrep: python.jwt.security.unverified-jwt-decode.unverified-jwt-decode
        claims = jwt.decode(assertion, options={"verify_signature": False})
    except jwt.PyJWTError:
        return ""
    subject = claims.get("sub") or ""
    return subject if isinstance(subject, str) else ""


def expected_assertion_audiences(*token_endpoint_paths: str) -> list[str]:
    """Audiences we accept, kept to an explicit set so an assertion minted for another
    service can't be replayed against us.

    RFC 7523 section 3 lets a client address either the issuer or the endpoint it is calling,
    so both are accepted. Callers pass the paths their own endpoint answers on.
    """
    site_url = settings.SITE_URL.rstrip("/")
    return [site_url, *(f"{site_url}{path}" for path in token_endpoint_paths)]


AGENTIC_TOKEN_ENDPOINT_PATH = "/api/agentic/oauth/token"


def describe_jwks(jwks_uri: str) -> list[str]:
    """Fetch and validate a key set, returning its key ids, for diagnostics.

    Always goes to the network so the answer reflects what the client is serving right now
    rather than what it served up to an hour ago. Raises ClientAssertionError with the reason
    the document was rejected, which is the whole point of calling this.
    """
    key_set = load_jwks(jwks_uri, force_refresh=True)
    return [key.key_id or "(no kid)" for key in key_set.keys]


def load_jwks(jwks_uri: str, *, force_refresh: bool = False) -> PyJWKSet:
    """Return the client's key set, cached, so a token exchange doesn't fetch on every call.

    Failures are cached too (briefly), so a client with a broken or hostile jwks_uri can't
    turn each of its requests into an outbound fetch.
    """
    cache_key = f"{JWKS_CACHE_PREFIX}{jwks_uri}"
    cached = None if force_refresh else cache.get(cache_key)
    if cached is not None:
        if cached == "error":
            raise ClientAssertionError("Client keys could not be retrieved")
        return PyJWKSet.from_dict(cached)

    try:
        parsed = _fetch_jwks_document(jwks_uri)
    except ClientAssertionError:
        cache.set(cache_key, "error", timeout=JWKS_NEGATIVE_CACHE_TTL_SECONDS)
        raise

    cache.set(cache_key, parsed, timeout=JWKS_CACHE_TTL_SECONDS)
    return PyJWKSet.from_dict(parsed)


def _fetch_jwks_document(jwks_uri: str) -> dict:
    """Fetch and validate the JWKS, raising ClientAssertionError on any rejection so the
    caller has a single place to record the negative cache entry."""
    try:
        parsed, _ = fetch_client_json_document(
            jwks_uri,
            what="JWKS",
            max_size=JWKS_MAX_DOCUMENT_SIZE,
            user_agent="PostHog-OAuth-JWKS/1.0",
            require_identity_url_shape=False,
        )
    except (CIMDFetchError, CIMDValidationError) as e:
        logger.warning("client_assertion_jwks_fetch_failed", jwks_uri=jwks_uri, error=str(e))
        raise ClientAssertionError("Client keys could not be retrieved") from e

    # Capping the key count keeps a hostile JWKS from making each verification walk a huge
    # set. Everything else about the document's shape is PyJWKSet's own validation.
    keys = parsed.get("keys")
    if isinstance(keys, list) and len(keys) > JWKS_MAX_KEYS:
        raise ClientAssertionError(f"JWKS must not contain more than {JWKS_MAX_KEYS} keys")

    try:
        PyJWKSet.from_dict(parsed)
    except Exception as e:
        raise ClientAssertionError(f"JWKS could not be parsed: {e}") from e

    return parsed


def _select_key(key_set: PyJWKSet, assertion: str) -> PyJWK:
    """Pick the key the assertion's header names, or the only key when it names none.

    Requiring a `kid` once the client publishes more than one key keeps verification from
    degrading into "try every key", which would let a rotated-out key keep working.
    """
    try:
        header = jwt.get_unverified_header(assertion)
    except jwt.PyJWTError as e:
        raise ClientAssertionError("Client assertion header is malformed") from e

    kid = header.get("kid")
    if kid:
        try:
            return key_set[kid]
        except KeyError as e:
            raise UnknownSigningKeyError("Client assertion is signed by an unknown key") from e

    if len(key_set.keys) == 1:
        return key_set.keys[0]
    raise ClientAssertionError("Client assertion must carry a kid when the JWKS holds several keys")


def _select_key_allowing_rotation(jwks_uri: str, assertion: str) -> PyJWK:
    """Select the assertion's signing key, re-fetching the JWKS once when the key is unknown.

    A client that rotates keys signs with the new ``kid`` while our cached copy of its key
    set still holds only the old ones, which would reject the client until the cache
    expires. The marker caps forced re-fetches at one per interval per URI.
    """
    try:
        return _select_key(load_jwks(jwks_uri), assertion)
    except UnknownSigningKeyError:
        marker = f"{JWKS_CACHE_PREFIX}rotation-refresh:{jwks_uri}"
        if not cache.add(marker, True, timeout=JWKS_ROTATION_REFRESH_MIN_INTERVAL_SECONDS):
            raise
        # Fetched directly rather than through load_jwks(force_refresh=True), whose failure
        # path writes the negative sentinel over the cached set: one assertion naming a bogus
        # kid while the client's JWKS endpoint is down would then lock out every assertion
        # signed with an already-cached key for the negative-cache window.
        parsed = _fetch_jwks_document(jwks_uri)
        cache.set(f"{JWKS_CACHE_PREFIX}{jwks_uri}", parsed, timeout=JWKS_CACHE_TTL_SECONDS)
        return _select_key(PyJWKSet.from_dict(parsed), assertion)


def _consume_jti(client_id: str, jti: str, expires_at: int) -> None:
    """Reject a replayed assertion. Scoped per client so one client cannot burn another's
    identifiers. Held until the assertion would have expired anyway, so the cache never has
    to outlive the window in which a replay would be accepted.
    """
    ttl = max(int(expires_at - time.time()) + ASSERTION_CLOCK_SKEW_SECONDS, 1)
    if not cache.add(f"{JTI_CACHE_PREFIX}{client_id}:{jti}", True, timeout=ttl):
        raise ClientAssertionError("Client assertion has already been used")


def verify_client_assertion(app: OAuthApplication, assertion: str, *, audiences: list[str] | None = None) -> None:
    """Verify a ``private_key_jwt`` assertion presented by ``app``, or raise.

    Checks, in order: the app has a published key source to verify against — confidential
    partners always have one, and a public CIMD client may too, once it starts signing; the
    signature verifies against that key under an asymmetric algorithm; the audience is us;
    ``iss`` and ``sub`` both identify this client (RFC 7523 section 3); the lifetime is
    bounded; and the ``jti`` has not been seen before.
    """
    if not app.jwks_uri:
        raise ClientAssertionError("This client is not registered for private_key_jwt authentication")

    key = _select_key_allowing_rotation(app.jwks_uri, assertion)
    # A CIMD client names itself by its metadata URL, not by the opaque client_id column, so
    # that is the identity its assertion carries.
    client_identifier = app.effective_client_id

    try:
        claims = jwt.decode(
            assertion,
            key=key,
            algorithms=ALLOWED_ASSERTION_ALGORITHMS,
            audience=audiences if audiences is not None else expected_assertion_audiences(AGENTIC_TOKEN_ENDPOINT_PATH),
            issuer=client_identifier,
            leeway=ASSERTION_CLOCK_SKEW_SECONDS,
            options={
                # iat is required so the lifetime cap below always has a lower bound to
                # measure against. Without it a client could set exp arbitrarily far out.
                "require": ["exp", "iat", "iss", "sub", "aud", "jti"],
                "verify_aud": True,
                "verify_exp": True,
            },
        )
    except jwt.PyJWTError as e:
        # The reason is logged rather than returned: which check failed is useful to us and
        # not something an unauthenticated caller needs.
        logger.warning("client_assertion_rejected", app_id=str(app.id), error=str(e), error_type=type(e).__name__)
        raise ClientAssertionError("Client assertion is invalid") from e

    # RFC 7523 section 3: for client authentication both iss and sub are the client_id.
    # `issuer` above covers iss; sub is checked here so an assertion minted to act as one
    # client cannot authenticate another.
    if claims.get("sub") != client_identifier:
        raise ClientAssertionError("Client assertion subject does not match the client")

    expires_at = claims["exp"]
    issued_at = claims["iat"]
    # PyJWT validates timestamps after int() coercion but hands back the original claim
    # values, so a numeric-string exp or iat survives decoding and would make the arithmetic
    # below a TypeError, surfacing as a 500 instead of invalid_client.
    if not isinstance(expires_at, (int, float)) or not isinstance(issued_at, (int, float)):
        raise ClientAssertionError("Client assertion timestamps must be numeric")
    if expires_at - issued_at > MAX_ASSERTION_LIFETIME_SECONDS:
        raise ClientAssertionError(f"Client assertion lifetime exceeds {MAX_ASSERTION_LIFETIME_SECONDS} seconds")

    _consume_jti(client_identifier, str(claims["jti"]), int(expires_at))
