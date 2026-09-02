import hmac
import hashlib
from collections.abc import Callable

# NUL separates claim fields so adjacent values cannot form an ambiguous signed input.
_CLAIM_SEP = "\x00"


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
    version: str = "v1",
) -> str:
    """HMAC-SHA256 over a signed identity claim.

    The signed input binds the base identity, field name, and version. This prevents replay
    under another identity and prevents a hash for one field from authorizing another field.
    """
    canonical = canonicalize_claim_value(field, value)
    parts = [version, distinct_id, field, canonical]
    if any(_CLAIM_SEP in part for part in parts):
        raise ValueError("Identity claim parts must not contain NUL characters")
    message = _CLAIM_SEP.join(parts)
    return hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()


def verify_identity_claim_hash(
    distinct_id: str,
    field: str,
    value: str,
    hash_value: str,
    secret: str,
    *,
    version: str = "v1",
) -> bool:
    """Verify a signed identity claim hash. Timing-safe."""
    try:
        expected = compute_identity_claim_hash(distinct_id, field, value, secret, version=version)
    except ValueError:
        return False
    return hmac.compare_digest(expected, hash_value)
