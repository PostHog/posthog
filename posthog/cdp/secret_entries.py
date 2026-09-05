"""Per-entry secrets inside a `dictionary` input.

A `secret: true` input is encrypted whole: the split, the read-back mask and the re-save recovery
all move one input's entire value. That is too coarse for a headers dictionary, where the names are
not credentials and only some values are, and it makes a partial update impossible - rewriting the
input to rotate one value would drop every other stored value in it.

So a dictionary input may instead declare, in `secret_keys`, which of its own entries are
credentials. Those entries' values (and their compiled bytecode, which embeds the value) live in the
encrypted store keyed by the same input key; the names and every other entry stay in the clear.

    inputs.headers           = {value: {"Content-Type": "..."}, secret_keys: ["Authorization"], ...}
    encrypted_inputs.headers = {value: {"Authorization": "Bearer ..."}, bytecode: {...}}

Whole-input secrets are untouched by any of this. An input is per-entry only when it carries
`secret_keys`.
"""

from dataclasses import field
from typing import Any, Optional

from posthog.dataclasses import frozen

SECRET_KEYS_FIELD = "secret_keys"


@frozen
class SplitInput:
    """One input's two halves. Named because swapping them would store the credentials in the clear."""

    public: dict
    secret: dict = field(repr=False)


def secret_entry_names(input_obj: Any) -> list[str]:
    """The entry names this input keeps encrypted. Empty for every input that is not per-entry."""
    if not isinstance(input_obj, dict):
        return []
    names = input_obj.get(SECRET_KEYS_FIELD)
    if not isinstance(names, list):
        return []
    return [name for name in names if isinstance(name, str) and name]


def has_secret_entries(input_obj: Any) -> bool:
    return bool(secret_entry_names(input_obj))


def _split_by_names(mapping: Any, names: list[str]) -> SplitInput:
    if not isinstance(mapping, dict):
        return SplitInput(public={}, secret={})
    return SplitInput(
        public={key: value for key, value in mapping.items() if key not in names},
        secret={key: value for key, value in mapping.items() if key in names},
    )


def split_secret_entries(input_obj: Any) -> SplitInput:
    """Split one per-entry input into its public half and its encrypted half.

    The public half keeps `secret_keys`, so a later read knows which rows to render as secret
    without their values, and a later split knows what to move again.
    """
    if not isinstance(input_obj, dict):
        return SplitInput(public={}, secret={})

    names = secret_entry_names(input_obj)
    value = _split_by_names(input_obj.get("value"), names)
    bytecode = _split_by_names(input_obj.get("bytecode"), names)

    public = {**input_obj, "value": value.public}
    if isinstance(input_obj.get("bytecode"), dict):
        public["bytecode"] = bytecode.public

    secret: dict[str, Any] = {"value": value.secret}
    if bytecode.secret:
        secret["bytecode"] = bytecode.secret

    return SplitInput(public=public, secret=secret)


def merge_secret_entries(public: Any, secret: Any) -> dict:
    """Rebuild a whole input from the two halves `split_secret_entries` produced."""
    if not isinstance(public, dict):
        return public
    if not isinstance(secret, dict):
        return public

    merged = {**public}
    merged["value"] = {**(public.get("value") or {}), **(secret.get("value") or {})}
    if isinstance(public.get("bytecode"), dict) or isinstance(secret.get("bytecode"), dict):
        merged["bytecode"] = {**(public.get("bytecode") or {}), **(secret.get("bytecode") or {})}
    return merged


def recover_secret_entries(incoming: Any, stored_secret: Optional[dict]) -> Any:
    """Fill in the secret entries a save did not resend.

    The editor only sends a secret entry's value when someone typed a new one, so an untouched
    entry arrives with its name in `secret_keys` and nothing in `value`. Its stored value has to be
    carried over, or saving an unrelated field would wipe the credential.
    """
    if not isinstance(incoming, dict):
        return incoming

    names = secret_entry_names(incoming)
    if not names:
        return incoming

    value = dict(incoming.get("value") or {})
    bytecode = incoming.get("bytecode")
    bytecode = dict(bytecode) if isinstance(bytecode, dict) else None

    stored_value = (stored_secret or {}).get("value") or {}
    stored_bytecode = (stored_secret or {}).get("bytecode") or {}

    for name in names:
        if name in value:
            continue
        if name in stored_value:
            value[name] = stored_value[name]
            if bytecode is not None and name in stored_bytecode:
                bytecode[name] = stored_bytecode[name]

    recovered = {**incoming, "value": value}
    if bytecode is not None:
        recovered["bytecode"] = bytecode
    return recovered


def missing_secret_entries(input_obj: Any, stored_secret: Optional[dict]) -> list[str]:
    """Declared secret entries with no value anywhere. A save with these would authenticate nothing."""
    names = secret_entry_names(input_obj)
    if not names:
        return []
    value = (input_obj or {}).get("value") or {}
    stored_value = (stored_secret or {}).get("value") or {}
    return [name for name in names if not value.get(name) and not stored_value.get(name)]
