"""The bearer-token scheme: a provider that authenticates with a JWT rather than an HMAC."""

from collections.abc import Callable, Mapping
from typing import Any

import jwt
import structlog

from posthog.dataclasses import frozen
from posthog.ingress.verify.schemes import Verification, VerificationOutcome, header_value

logger = structlog.get_logger(__name__)

# PyJWT defaults to 30 seconds, which holds a webhook request open long after the provider
# gave up on it. The same value guards the JWKS fetch in `posthog/api/id_jag.py`.
_JWKS_FETCH_TIMEOUT_SECONDS = 10

# The client holds the key cache, so one per URI rather than one per request. The URIs are fixed
# by the incarnations mounted in the process, which is why nothing evicts here.
_JWKS_CLIENTS: dict[str, jwt.PyJWKClient] = {}

# The scheme writes this fact after the claims, so a token that carries a claim of the same name
# cannot put its own value here.
SIGNING_KEY_FACT = "signing_key"


def _signing_key_members(signing_key: jwt.PyJWK) -> Mapping[str, Any]:
    """The key as the JWKS published it, including the members PyJWT does not model.

    PyJWT keeps the decoded JWK on the key object and offers no accessor for it, so this reads the
    attribute it holds it in. `test_verify.py` pins that against a real JWKS document.
    """
    members = getattr(signing_key, "_jwk_data", None)
    return members if isinstance(members, Mapping) else {}


def _jwks_client(jwks_uri: str) -> jwt.PyJWKClient:
    client = _JWKS_CLIENTS.get(jwks_uri)
    if client is None:
        client = jwt.PyJWKClient(jwks_uri, timeout=_JWKS_FETCH_TIMEOUT_SECONDS)
        _JWKS_CLIENTS[jwks_uri] = client
    return client


@frozen
class BearerJwt:
    """A bearer token signed as a JWT, checked against the signing keys the issuer publishes.

    Every provider-specific value arrives as a callable, so the scheme itself holds no URL, no
    app id and no issuer. That also keeps the provider's discovery out of here: Bot Framework
    publishes its `jwks_uri` in an OpenID metadata document, and fetching that document is the
    incarnation's `jwks_uri_getter`, not this scheme's job. A getter that fetches must cache its
    own answer, because `verify` calls it on every delivery.

    The verified claims become `facts`, because a signed token proves more than "this is really
    them". It names the sender and the audience, so `deliveries` can hold the body to what the
    issuer actually signed rather than to a field of the body that claims the same thing. The key
    that signed it joins them under `SIGNING_KEY_FACT`, because a JWKS can say what one key is
    allowed to sign and the token cannot.
    """

    jwks_uri_getter: Callable[[], str | None]
    audience_getter: Callable[[], str | None]
    issuers_getter: Callable[[], frozenset[str]]
    algorithms: tuple[str, ...] = ("RS256",)
    leeway_seconds: int = 300
    token_header: str = "Authorization"
    token_prefix: str = "Bearer "

    def _token(self, headers: Mapping[str, str]) -> str | None:
        provided = header_value(headers, self.token_header)
        if not provided or not provided.startswith(self.token_prefix):
            return None
        # A prefix with nothing behind it is no credential, so it is refused from the header
        # alone rather than sent to the JWKS fetch to fail there.
        return provided[len(self.token_prefix) :].strip() or None

    def rejects_headers(self, headers: Mapping[str, str]) -> bool:
        return self._token(headers) is None

    def verify(self, *, body: bytes, headers: Mapping[str, str]) -> Verification:
        # The header comes before the getters, unlike the HMAC scheme, because a getter that
        # discovers its `jwks_uri` costs an HTTP request a token-less probe must not buy.
        token = self._token(headers)
        if token is None:
            return Verification(outcome=VerificationOutcome.INVALID)

        audience = self.audience_getter()
        issuers = self.issuers_getter()
        # An empty issuer allowlist rejects every token that will ever arrive, so it is an
        # operator problem rather than a caller one, the same as a missing secret. Both are read
        # before the URI, so an instance that was never set up buys no discovery request.
        if not audience or not issuers:
            return Verification(outcome=VerificationOutcome.NOT_CONFIGURED)

        jwks_uri = self.jwks_uri_getter()
        if not jwks_uri:
            # The getter discovers this URI remotely, so no URI reads as a discovery that failed
            # rather than as an instance nobody configured. It is the same answer as a JWKS fetch
            # that never completed: the check did not run, and a provider that retries a server
            # error sends the delivery again. A provider whose unconfigured status is a 4xx would
            # otherwise drop every delivery for the length of the issuer's outage.
            logger.warning("ingress_jwt_signing_key_uri_unavailable")
            return Verification(outcome=VerificationOutcome.UNAVAILABLE)

        try:
            signing_key = _jwks_client(jwks_uri).get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=list(self.algorithms),
                audience=audience,
                issuer=issuers,
                leeway=self.leeway_seconds,
                # Without this, a token that carries no `exp` never expires.
                options={"require": ["exp"]},
            )
        except jwt.PyJWKClientConnectionError as error:
            # The JWKS fetch never completed, so the token was never checked. INVALID here hands a
            # 403 to a provider that retries server errors only, which drops a valid delivery for
            # good over a DNS blip or a JWKS outage.
            logger.warning("ingress_jwt_signing_keys_unreachable", error_type=type(error).__name__)
            return Verification(outcome=VerificationOutcome.UNAVAILABLE)
        except jwt.PyJWKClientError as error:
            # The JWKS was read and holds no key this token can use, which is the token's problem.
            logger.warning("ingress_jwt_signing_key_unavailable", error_type=type(error).__name__)
            return Verification(outcome=VerificationOutcome.INVALID)
        except jwt.InvalidTokenError as error:
            # The error class alone: the token is a credential and its claims are the caller's
            # data, so neither belongs in a log an unauthenticated request drives.
            logger.warning("ingress_jwt_rejected", error_type=type(error).__name__)
            return Verification(outcome=VerificationOutcome.INVALID)

        return Verification(
            outcome=VerificationOutcome.VERIFIED,
            facts={**claims, SIGNING_KEY_FACT: _signing_key_members(signing_key)},
        )
