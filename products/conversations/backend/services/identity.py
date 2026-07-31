import hmac
import hashlib


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


def compute_identity_email_hash(distinct_id: str, email: str, secret: str) -> str:
    """Compute HMAC-SHA256 of an email claim bound to a distinct_id."""
    return hmac.new(
        secret.encode(),
        f"{distinct_id}:{email}".encode(),
        hashlib.sha256,
    ).hexdigest()


def verify_identity_email_hash(distinct_id: str, email: str, hash_value: str, secret: str) -> bool:
    """Verify an HMAC email-claim hash. Timing-safe."""
    expected = compute_identity_email_hash(distinct_id, email, secret)
    return hmac.compare_digest(expected, hash_value)
