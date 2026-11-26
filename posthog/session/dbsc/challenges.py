import hmac
import hashlib
import secrets

from django.core.cache import BaseCache, caches

# A refresh that waited longer than this asks for a new challenge, so a captured proof goes stale.
CHALLENGE_TTL_SECONDS = 5 * 60
_CACHE_PREFIX = "dbsc_challenge:"


def _store() -> BaseCache:
    return caches["dbsc_challenges"]


def _cache_key(subject: str) -> str:
    return _CACHE_PREFIX + hashlib.sha256(subject.encode()).hexdigest()


def registration_subject(offer_id: str) -> str:
    return f"offer:{offer_id}"


def refresh_subject(binding_id: str) -> str:
    return f"binding:{binding_id}"


def issue_challenge(subject: str) -> str:
    """Keyed by an offer or binding id, because the response to a login has no session key yet."""
    key = _cache_key(subject)
    store = _store()
    store.add(key, secrets.token_urlsafe(32), CHALLENGE_TTL_SECONDS)
    challenge = store.get(key)
    if not isinstance(challenge, str):
        challenge = secrets.token_urlsafe(32)
        store.set(key, challenge, CHALLENGE_TTL_SECONDS)
    return challenge


def consume_challenge(subject: str, challenge: str) -> bool:
    key = _cache_key(subject)
    store = _store()
    stored = store.get(key)
    # Bytes, because compare_digest raises on a str with non-ASCII characters, and the proof is caller input.
    if not isinstance(stored, str) or not hmac.compare_digest(stored.encode(), challenge.encode()):
        return False
    # Only one of two concurrent requests with the same proof deletes the key.
    return bool(store.delete(key))
