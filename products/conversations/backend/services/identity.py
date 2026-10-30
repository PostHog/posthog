import hmac
import time
import uuid
import hashlib
from collections.abc import Callable

from posthog.dataclasses import frozen

# NUL separates claim fields so adjacent values cannot form an ambiguous signed input.
_CLAIM_SEP = "\x00"
IDENTITY_CLAIM_MAX_AGE_SECONDS = 24 * 60 * 60
_IDENTITY_CLAIM_CLOCK_SKEW_SECONDS = 5 * 60


def compute_identity_hash(distinct_id: str, secret: str) -> str:
    """Compute HMAC-SHA256 of a distinct_id using the team's secret."""
    return hmac.new(
        secret.encode(),
        distinct_id.encode(),
        hashlib.sha256,
    ).hexdigest()


def verify_identity_hash(distinct_id: str, hash_value: str, secret: str) -> bool:
    """Verify an HMAC identity hash. Timing-safe."""
    expected = compute_identity_hash(distinct_id, secret)
    return hmac.compare_digest(expected, hash_value)


def _canonicalize_email(value: str) -> str:
    return value.strip().lower()


# Per-field rule to canonicalize a claim value before it is signed or verified. The rule runs
# identically at sign time and verify time, so the signature never depends on formatting the
# client happened to send. Keep this an explicit map: a field with no rule here cannot be
# signed or verified, which stops an unaudited claim from slipping through the generic path.
_CLAIM_CANONICALIZERS: dict[str, Callable[[str], str]] = {
    "email": _canonicalize_email,
}


def canonicalize_claim_value(field: str, value: str) -> str:
    """Return the canonical form of a claim value for the given field.

    Raises ValueError for a field with no registered rule, so an unknown claim can never be
    signed or verified by accident.
    """
    try:
        canonicalize = _CLAIM_CANONICALIZERS[field]
    except KeyError:
        raise ValueError(f"No canonicalizer registered for identity claim field {field!r}")
    return canonicalize(value)


def compute_identity_claim_hash(
    distinct_id: str,
    field: str,
    value: str,
    secret: str,
    *,
    expires_at: int,
    version: str = "v1",
) -> str:
    """HMAC-SHA256 over a signed identity claim.

    The signed input binds the base identity, field name, expiry, and version. This prevents
    cross-identity replay, field confusion, and indefinite reuse of a leaked claim.
    """
    canonical = canonicalize_claim_value(field, value)
    parts = [version, distinct_id, field, canonical, str(expires_at)]
    if any(_CLAIM_SEP in part for part in parts):
        raise ValueError("Identity claim parts must not contain NUL characters")
    message = _CLAIM_SEP.join(parts)
    return hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()


def identity_claim_has_expired(expires_at: int, *, now: int | None = None) -> bool:
    current_time = int(time.time()) if now is None else now
    return expires_at <= current_time


def verify_identity_claim_hash(
    distinct_id: str,
    field: str,
    value: str,
    hash_value: str,
    secret: str,
    *,
    expires_at: int,
    version: str = "v1",
    now: int | None = None,
) -> bool:
    """Verify a signed identity claim hash. Timing-safe."""
    current_time = int(time.time()) if now is None else now
    if identity_claim_has_expired(expires_at, now=current_time):
        return False
    if expires_at > current_time + IDENTITY_CLAIM_MAX_AGE_SECONDS + _IDENTITY_CLAIM_CLOCK_SKEW_SECONDS:
        return False
    try:
        expected = compute_identity_claim_hash(
            distinct_id,
            field,
            value,
            secret,
            expires_at=expires_at,
            version=version,
        )
    except ValueError:
        return False
    return hmac.compare_digest(expected, hash_value)


@frozen
class SignedIdentityClaim:
    value: str
    expires_at: int
    hash: str


@frozen
class SignedIdentity:
    distinct_id: str
    hash: str
    email: SignedIdentityClaim | None


def sign_identity(distinct_id: str, secret: str, *, verified_email: str | None) -> SignedIdentity:
    """Sign a PostHog user's identity for PostHog's own support widget.

    The web app and the MCP support tools both send this, so the widget must see the same
    identity from either surface. Pass an email only when the user has verified it.
    """
    email_claim = None
    if verified_email:
        canonical_email = canonicalize_claim_value("email", verified_email)
        expires_at = int(time.time()) + IDENTITY_CLAIM_MAX_AGE_SECONDS
        email_claim = SignedIdentityClaim(
            value=canonical_email,
            expires_at=expires_at,
            hash=compute_identity_claim_hash(distinct_id, "email", canonical_email, secret, expires_at=expires_at),
        )
    return SignedIdentity(distinct_id=distinct_id, hash=compute_identity_hash(distinct_id, secret), email=email_claim)


def widget_session_id_for_identity(identity_hash: str) -> str:
    """The widget session id that a verified identity's tickets are stored under."""
    return str(uuid.UUID(identity_hash[:32]))
