"""Python mirror of the session replay ML mirror's pseudonymization.

The Node.js ingester (`nodejs/src/ingestion/pipelines/sessionreplay/ml-mirror/
pseudonymize.ts` + `pseudonym-key.ts`) is the source of truth; this module
must produce byte-identical pseudonyms from the same key, or exported scores
won't join onto the mirrored replay dataset. Same key resolution too:
KMS-wrapped key in prod, plaintext env for local dev, pinned fingerprint so a
rotated key can't silently re-map the id space.
"""

from __future__ import annotations

import os
import hmac
import hashlib
import threading
from base64 import b64decode

import structlog
from boto3 import client as boto3_client

logger = structlog.get_logger(__name__)

PSEUDONYM_TEAM = "team"
PSEUDONYM_SESSION = "session"

WRAPPED_KEY_ENV_VAR = "SESSION_RECORDING_ML_PSEUDONYM_WRAPPED_KEY"
PLAINTEXT_SECRET_ENV_VAR = "SESSION_RECORDING_ML_PSEUDONYM_SECRET"
KMS_REGION_ENV_VAR = "SESSION_RECORDING_ML_PSEUDONYM_KMS_REGION"
KEY_FINGERPRINT_ENV_VAR = "SESSION_RECORDING_ML_PSEUDONYM_KEY_FINGERPRINT"


class PseudonymKeyNotConfiguredError(RuntimeError):
    """Neither the KMS-wrapped key nor the plaintext dev secret is set."""


class PseudonymKeyFingerprintMismatchError(RuntimeError):
    """The resolved key doesn't match the pinned fingerprint."""


def pseudonymize(secret: bytes, namespace: str, value: str) -> str:
    """Deterministic, non-reversible pseudonym for an identifier.

    Byte-identical to the Node implementation: HMAC-SHA256 over the
    length-prefixed namespace + value, hex, truncated to 32 chars.
    """
    message = f"{len(namespace)}:{namespace}:{value}".encode()
    return hmac.new(secret, message, hashlib.sha256).hexdigest()[:32]


def pseudonym_key_fingerprint(secret: bytes) -> str:
    """Non-reversible fingerprint of the key — safe to log, pins the id space to one key."""
    return hmac.new(secret, b"pseudonym-key-fingerprint:v1", hashlib.sha256).hexdigest()[:16]


def is_pseudonym_key_configured() -> bool:
    return bool(os.environ.get(WRAPPED_KEY_ENV_VAR) or os.environ.get(PLAINTEXT_SECRET_ENV_VAR))


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
    """Resolve the HMAC key once per process: KMS-wrapped ciphertext preferred, plaintext env for dev.

    Fails closed when no key is configured, or when the pinned fingerprint
    doesn't match — a rotated/incorrect key would re-map every id and the
    exported scores would join onto nothing.
    """
    global _SECRET
    with _SECRET_LOCK:
        if _SECRET is not None:
            return _SECRET

        wrapped = os.environ.get(WRAPPED_KEY_ENV_VAR)
        plaintext_secret = os.environ.get(PLAINTEXT_SECRET_ENV_VAR)
        if wrapped:
            secret = _kms_decrypt(wrapped, os.environ.get(KMS_REGION_ENV_VAR, ""))
            source = "kms"
        elif plaintext_secret:
            secret = plaintext_secret.encode()
            source = "env"
        else:
            raise PseudonymKeyNotConfiguredError(
                f"{WRAPPED_KEY_ENV_VAR} or {PLAINTEXT_SECRET_ENV_VAR} must be set for the score export sweep"
            )

        fingerprint = pseudonym_key_fingerprint(secret)
        expected = os.environ.get(KEY_FINGERPRINT_ENV_VAR)
        if expected and expected != fingerprint:
            raise PseudonymKeyFingerprintMismatchError(
                f"pseudonym key fingerprint mismatch (resolved {fingerprint}, expected {expected}) — "
                "refusing to export: a rotated/incorrect key would re-map ids away from the ML mirror dataset"
            )

        logger.info(
            "surfacing_score_export_sweep.pseudonym_key_loaded",
            source=source,
            fingerprint=fingerprint,
            pinned=bool(expected),
        )
        _SECRET = secret
        return secret
