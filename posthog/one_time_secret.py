import json
import base64
import secrets
from typing import Optional

from django.conf import settings

from cryptography.fernet import Fernet, MultiFernet

from posthog.redis import get_client

# One-time secrets are shown to a human exactly once via a reveal URL, then burned.
# They live only in Redis (never Postgres), encrypted at rest, and expire after this window.
ONE_TIME_SECRET_TTL_SECONDS = 30 * 60

_REDIS_KEY_PREFIX = "one_time_secret:"


class OneTimeSecretType:
    """The kind of secret being revealed. Drives type-specific copy on the reveal page.

    Keep in sync with the frontend `OneTimeSecretType` copy map.
    """

    PERSONAL_API_TOKEN = "personal_api_token"

    ALL = {PERSONAL_API_TOKEN}


def _cipher() -> Fernet | MultiFernet:
    # Reuse the app's symmetric field-encryption keys (same as EncryptedJSONField).
    keys = [base64.urlsafe_b64encode(key.encode("utf-8")) for key in settings.ENCRYPTION_SALT_KEYS]
    if len(keys) == 1:
        return Fernet(keys[0])
    return MultiFernet([Fernet(key) for key in keys])


def _redis_key(token: str) -> str:
    return f"{_REDIS_KEY_PREFIX}{token}"


def create_one_time_secret(
    *,
    value: str,
    secret_type: str,
    created_by_id: int,
    ttl_seconds: int = ONE_TIME_SECRET_TTL_SECONDS,
) -> str:
    """Store a secret for a single, human-only reveal and return its opaque token.

    The value is encrypted at rest and never persisted outside Redis. Build the reveal URL
    with `build_reveal_url(token)`.
    """
    if secret_type not in OneTimeSecretType.ALL:
        raise ValueError(f"Unknown one-time secret type: {secret_type}")

    token = secrets.token_urlsafe(32)
    payload = json.dumps(
        {
            "type": secret_type,
            "created_by_id": created_by_id,
            "value": _cipher().encrypt(value.encode("utf-8")).decode("utf-8"),
        }
    )
    get_client().set(_redis_key(token), payload, ex=ttl_seconds)
    return token


def peek_one_time_secret(token: str, *, user_id: int) -> Optional[dict]:
    """Return `{ "type": ... }` if the token is live and owned by this user, without consuming it.

    Used to render the reveal page (type-specific copy + availability) before the human reveals.
    Returns None for missing/expired tokens and for tokens belonging to another user, so a leaked
    URL discloses nothing to anyone but the rightful owner.
    """
    raw = get_client().get(_redis_key(token))
    if not raw:
        return None
    data = json.loads(raw)
    if data.get("created_by_id") != user_id:
        return None
    return {"type": data["type"]}


def consume_one_time_secret(token: str, *, user_id: int) -> Optional[dict]:
    """Reveal the secret exactly once, then burn it. Returns `{ "type", "value" }` or None.

    Returns None when the token is missing/expired, already consumed, or belongs to another user —
    the mismatched-user case deliberately does not burn the token, so the rightful owner can still
    reveal it.
    """
    client = get_client()
    key = _redis_key(token)
    raw = client.get(key)
    if not raw:
        return None

    data = json.loads(raw)
    if data.get("created_by_id") != user_id:
        return None

    client.delete(key)
    value = _cipher().decrypt(data["value"].encode("utf-8")).decode("utf-8")
    return {"type": data["type"], "value": value}


def build_reveal_url(token: str) -> str:
    return f"{settings.SITE_URL}/reveal/{token}"
