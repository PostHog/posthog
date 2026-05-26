"""Helpers for encrypting/decrypting secret inputs inline within HogFlow action configs.

HogFunction stores secrets in a separate `encrypted_inputs` column (an EncryptedJSONStringField).
HogFlow does not — its `actions` JSON column carries every action's inputs together. To support
destinations with secret inputs in workflows we therefore encrypt those values *inline*: the
sensitive value is replaced with `{"__ph_encrypted": "<fernet_token>"}` in storage.

The same nodejs runtime reads the encryption keys (`ENCRYPTION_SALT_KEYS`) so it can decrypt
these values when it builds a HogFunction from a HogFlow action.
"""

import json
from typing import Any, Optional

from posthog.helpers.encrypted_fields import EncryptedTextField

# Marker key embedded inside an input value to indicate the contents have been Fernet-encrypted.
# Kept in sync with the nodejs side (nodejs/src/cdp/utils/encryption-utils.ts).
INLINE_ENCRYPTED_MARKER = "__ph_encrypted"


# `EncryptedTextField` exposes `.encrypt()` / `.decrypt()` that share the same Fernet/MultiFernet
# wiring as the model-level encrypted fields, so secrets here are compatible with what the nodejs
# runtime (and HogFunction's encrypted_inputs) decrypts.
_encryptor = EncryptedTextField()


def _is_encrypted_value(value: Any) -> bool:
    return isinstance(value, dict) and isinstance(value.get(INLINE_ENCRYPTED_MARKER), str)


def _encrypt_value(value: Any) -> dict[str, str]:
    return {INLINE_ENCRYPTED_MARKER: _encryptor.encrypt(json.dumps(value))}


def _secret_keys(inputs_schema: list[dict[str, Any]] | None) -> set[str]:
    if not inputs_schema:
        return set()
    return {str(s["key"]) for s in inputs_schema if s.get("secret") and "key" in s}


def encrypt_secret_inputs(
    inputs: dict[str, Any] | None,
    inputs_schema: list[dict[str, Any]] | None,
    existing_inputs: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Return a new inputs dict where every secret field's value is Fernet-encrypted in place.

    Resilience rules:
    - Values that are already encrypted are kept as-is (allows partial-update writes).
    - If the incoming value is missing/empty AND the existing stored value is encrypted, the
      existing encrypted value is preserved (so PATCH-style updates don't wipe the secret).
    - Non-secret inputs pass through unchanged.
    """

    if not inputs:
        return inputs or {}

    secret_keys = _secret_keys(inputs_schema)
    if not secret_keys:
        return inputs

    existing = existing_inputs or {}
    result: dict[str, Any] = {}
    for key, item in inputs.items():
        if key not in secret_keys or not isinstance(item, dict):
            result[key] = item
            continue

        value = item.get("value")
        is_empty = value in (None, "", {})
        existing_item = existing.get(key) if isinstance(existing, dict) else None
        existing_value = existing_item.get("value") if isinstance(existing_item, dict) else None

        if _is_encrypted_value(value):
            # Already encrypted (e.g. round-tripped from storage) — keep verbatim.
            result[key] = item
        elif is_empty and _is_encrypted_value(existing_value):
            # Caller left the secret untouched — preserve what we already have.
            merged = {**item, "value": existing_value}
            result[key] = merged
        elif is_empty:
            # No previous value and nothing to encrypt — store the item as-is.
            result[key] = item
        else:
            # Strip bytecode/templating: secret values are never templated and we don't want
            # plaintext-derived bytecode to remain alongside the encrypted blob.
            stripped = {k: v for k, v in item.items() if k not in ("bytecode", "transpiled", "input_deps")}
            stripped["value"] = _encrypt_value(value)
            result[key] = stripped

    return result


def mask_secret_inputs_for_read(
    inputs: dict[str, Any] | None,
    inputs_schema: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """Replace any secret input's value with the `{secret: true}` placeholder used by the
    frontend. Plaintext secrets — encrypted or, defensively, anything that ever slipped in
    unencrypted — never reach the client.
    """

    if not inputs:
        return inputs or {}

    secret_keys = _secret_keys(inputs_schema)
    if not secret_keys:
        return inputs

    result: dict[str, Any] = {}
    for key, item in inputs.items():
        if key in secret_keys and isinstance(item, dict) and item.get("value") not in (None, "", {}):
            result[key] = {"secret": True}
        else:
            result[key] = item
    return result
