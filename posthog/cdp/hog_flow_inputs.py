"""Helpers for encrypting/decrypting secret inputs inline within HogFlow action configs.

HogFunction stores secrets in a separate `encrypted_inputs` column (an EncryptedJSONStringField).
HogFlow does not — its `actions` JSON column carries every action's inputs together. To support
destinations with secret inputs in workflows we therefore encrypt those values *inline*: the
sensitive value is replaced with the Fernet ciphertext string at the same `value` slot.

The schema (`inputs_schema[i].secret == True`) is the sole signal for "this value is encrypted."
The same nodejs runtime reads the encryption keys (`ENCRYPTION_SALT_KEYS`) so it can decrypt
these values when it builds a HogFunction from a HogFlow action.
"""

import json
from typing import Any, Optional

from posthog.helpers.encrypted_fields import EncryptedTextField

# `EncryptedTextField` exposes `.encrypt()` / `.decrypt()` that share the same Fernet/MultiFernet
# wiring as the model-level encrypted fields, so secrets here are compatible with what the nodejs
# runtime (and HogFunction's encrypted_inputs) decrypts.
_encryptor = EncryptedTextField()


def _secret_keys(inputs_schema: list[dict[str, Any]] | None) -> set[str]:
    if not inputs_schema:
        return set()
    return {str(s["key"]) for s in inputs_schema if s.get("secret") and "key" in s}


def _encrypt_value(value: Any) -> str:
    return _encryptor.encrypt(json.dumps(value))


def _looks_like_ciphertext(value: Any) -> bool:
    """Return True if `value` is a string that Fernet-decrypts cleanly under the current keys.

    Used to distinguish "stored ciphertext round-tripping through a save" (pass through)
    from "fresh plaintext on the way in" (encrypt). Fernet tokens are HMAC-authenticated,
    so a random string has effectively zero probability of decrypting successfully.
    """
    if not isinstance(value, str):
        return False
    try:
        _encryptor.decrypt(value)
        return True
    except Exception:
        return False


def resolve_secret_inputs(
    inputs: dict[str, Any] | None,
    inputs_schema: list[dict[str, Any]] | None,
    existing_inputs: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Compute the final stored shape for every secret-flagged schema key.

    Secret inputs arrive in four shapes and each maps to a single resolved value:

    - **Already-encrypted ciphertext** (string that decrypts cleanly under current keys) → kept
      verbatim. Covers draft → active re-validation and server-initiated round-trips.
    - **Placeholder** (`{"secret": True}` or empty value — frontend marker for "user didn't
      touch this") → restored from `existing_inputs` if there's a prior encrypted value, or
      kept as-is otherwise.
    - **Missing entirely** (key absent from `inputs` because the frontend stripped it from
      the outgoing payload) → restored from `existing_inputs` if there's a prior encrypted
      value, or omitted from the result entirely.
    - **Fresh plaintext** → Fernet-encrypted in place. Bytecode/templating siblings are
      stripped because secrets are never templated and a plaintext-derived bytecode
      alongside an encrypted blob would be misleading.

    Returns a new dict keyed only by secret schema keys. Caller is expected to merge it
    with separately-validated non-secret inputs. Non-secret keys present in the input dict
    are ignored — this function is purely about resolving secrets.
    """

    secret_keys = _secret_keys(inputs_schema)
    if not secret_keys:
        return {}

    inputs = inputs or {}
    existing = existing_inputs or {}
    result: dict[str, Any] = {}

    for key in secret_keys:
        incoming_raw = inputs.get(key)
        incoming = incoming_raw if isinstance(incoming_raw, dict) else None
        existing_item_raw = existing.get(key)
        existing_item = existing_item_raw if isinstance(existing_item_raw, dict) else None
        existing_value = existing_item.get("value") if existing_item else None

        if incoming is None:
            # Key absent from the request. Preserve any prior encrypted value; otherwise
            # leave the secret unset.
            if _looks_like_ciphertext(existing_value):
                result[key] = existing_item
            continue

        incoming_value = incoming.get("value")
        is_placeholder = incoming.get("secret") is True or incoming_value in (None, "", {})

        if is_placeholder:
            # User didn't change the secret. Restore the prior stored item verbatim;
            # otherwise fall back to whatever the caller sent (empty/placeholder).
            if existing_item is not None and _looks_like_ciphertext(existing_value):
                result[key] = existing_item
            else:
                result[key] = incoming
            continue

        if _looks_like_ciphertext(incoming_value) and incoming_value == existing_value:
            # True round-trip: the incoming ciphertext matches what's already stored. Keep
            # verbatim (covers draft → active re-validation and server-initiated resubmits).
            #
            # If the ciphertexts don't match we deliberately fall through to the encrypt
            # branch: any other valid ciphertext came from outside this row (a leaked
            # backup, a different workflow, a copy-paste) and silently accepting it would
            # let a workflow editor swap in someone else's secret. Re-encrypting as fresh
            # plaintext makes the user's intent explicit — they typed a literal string,
            # we store a literal string.
            result[key] = incoming
            continue

        # Fresh plaintext — encrypt. Strip templating siblings: secrets are never templated
        # and we don't want plaintext-derived bytecode living alongside the ciphertext.
        stripped = {k: v for k, v in incoming.items() if k not in ("bytecode", "transpiled", "input_deps")}
        stripped["value"] = _encrypt_value(incoming_value)
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
