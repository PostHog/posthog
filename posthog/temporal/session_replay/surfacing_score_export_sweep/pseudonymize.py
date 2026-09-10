"""Legacy identifier hashing, matching the ML mirror's pseudonymization (`nodejs/.../ml-mirror/pseudonymize.ts`
+ `pseudonym-key.ts`). Must stay byte-identical, same key and env vars, or exported
scores stop joining onto the mirrored dataset."""

from __future__ import annotations

import hmac
import hashlib
import threading
from base64 import b64decode

import structlog
from boto3 import client as boto3_client

from posthog.temporal.session_replay.surfacing_score_export_sweep.env import get_ai_research_replay_env

logger = structlog.get_logger(__name__)

PSEUDONYM_TEAM = "team"
PSEUDONYM_SESSION = "session"

WRAPPED_KEY_ENV_VAR = "AI_RESEARCH_REPLAY_PSEUDONYM_WRAPPED_KEY"
PLAINTEXT_SECRET_ENV_VAR = "AI_RESEARCH_REPLAY_PSEUDONYM_SECRET"
KMS_REGION_ENV_VAR = "AI_RESEARCH_REPLAY_PSEUDONYM_KMS_REGION"
KEY_FINGERPRINT_ENV_VAR = "AI_RESEARCH_REPLAY_PSEUDONYM_KEY_FINGERPRINT"


class PseudonymKeyNotConfiguredError(RuntimeError):
    pass


class PseudonymKeyFingerprintMismatchError(RuntimeError):
    pass


def pseudonymize(secret: bytes, namespace: str, value: str) -> str:
    message = f"{len(namespace)}:{namespace}:{value}".encode()
    return hmac.new(secret, message, hashlib.sha256).hexdigest()[:32]


def pseudonym_key_fingerprint(secret: bytes) -> str:
    return hmac.new(secret, b"pseudonym-key-fingerprint:v1", hashlib.sha256).hexdigest()[:16]


def is_pseudonym_key_configured() -> bool:
    return bool(get_ai_research_replay_env(WRAPPED_KEY_ENV_VAR) or get_ai_research_replay_env(PLAINTEXT_SECRET_ENV_VAR))


_SECRET: bytes | None = None
_SECRET_LOCK = threading.Lock()


def _kms_decrypt(ciphertext_base64: str, region: str) -> bytes:
    kms = boto3_client("kms", region_name=region or None)
    result = kms.decrypt(CiphertextBlob=b64decode(ciphertext_base64))
    plaintext = result.get("Plaintext")
    if not plaintext:
        raise PseudonymKeyNotConfiguredError("KMS Decrypt returned no plaintext for the pseudonym key")
    return bytes(plaintext)


def resolve_pseudonym_key() -> bytes:
    """KMS-wrapped key preferred, plaintext env for dev. Fails closed on a missing key
    or a pinned-fingerprint mismatch — a rotated key would re-map the id space."""
    global _SECRET
    with _SECRET_LOCK:
        if _SECRET is not None:
            return _SECRET

        wrapped = get_ai_research_replay_env(WRAPPED_KEY_ENV_VAR)
        plaintext_secret = get_ai_research_replay_env(PLAINTEXT_SECRET_ENV_VAR)
        if wrapped:
            secret = _kms_decrypt(wrapped, get_ai_research_replay_env(KMS_REGION_ENV_VAR, ""))
            source = "kms"
        elif plaintext_secret:
            secret = plaintext_secret.encode()
            source = "env"
        else:
            raise PseudonymKeyNotConfiguredError(
                f"{WRAPPED_KEY_ENV_VAR} or {PLAINTEXT_SECRET_ENV_VAR} must be set for the score export sweep"
            )

        fingerprint = pseudonym_key_fingerprint(secret)
        expected = get_ai_research_replay_env(KEY_FINGERPRINT_ENV_VAR)
        if expected and expected != fingerprint:
            raise PseudonymKeyFingerprintMismatchError(
                f"pseudonym key fingerprint mismatch (resolved {fingerprint}, expected {expected})"
            )

        logger.info(
            "surfacing_score_export_sweep.pseudonym_key_loaded",
            source=source,
            fingerprint=fingerprint,
            pinned=bool(expected),
        )
        _SECRET = secret
        return secret
