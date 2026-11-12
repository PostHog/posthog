"""The saves that must carry a function's stored secret inputs typed again.

A secret input is typed into one function, and the code reads its value. A change to the code, the inputs or the
mappings could send it anywhere, so such a change must carry every stored secret typed again. The stored secret then
only ever runs with code that someone who knows it saved.
"""

import json
from enum import StrEnum
from typing import Any, Optional


class SecretReentry(StrEnum):
    REENTERED = "reentered"
    REFUSED = "refused"
    WOULD_REFUSE = "would_refuse"
    STAGED = "staged"


def stored_secrets(inputs: Optional[dict], inputs_schema: Optional[list], encrypted_inputs: Optional[dict]) -> dict:
    """Every secret the worker resolves for a stored function. A secret saved before inputs were encrypted is still
    in plaintext `inputs`, and the worker merges both columns by name."""
    plaintext = inputs if isinstance(inputs, dict) else {}
    secret_keys = {
        schema.get("key") for schema in inputs_schema or [] if isinstance(schema, dict) and schema.get("secret")
    }
    return {
        **{key: entry for key, entry in plaintext.items() if key in secret_keys and isinstance(entry, dict)},
        **{key: entry for key, entry in (encrypted_inputs or {}).items() if isinstance(entry, dict)},
    }


def mapping_secret_values(mappings: Any) -> dict[str, set[str]]:
    """Secrets saved in plaintext mapping inputs before mappings refused secret inputs, as the JSON values stored under
    each key. The worker lays each mapping's inputs over the function's, so the code reads them by name."""
    values: dict[str, set[str]] = {}
    for mapping in mappings or []:
        if not isinstance(mapping, dict) or not isinstance(mapping.get("inputs"), dict):
            continue
        for schema in mapping.get("inputs_schema") or []:
            if isinstance(schema, dict) and schema.get("secret"):
                key = str(schema.get("key"))
                entry = mapping["inputs"].get(key)
                if isinstance(entry, dict) and entry.get("value") not in (None, "", {}):
                    values.setdefault(key, set()).add(json.dumps(entry["value"], default=str, sort_keys=True))
    return values


def carried_mapping_secrets(stored: dict[str, set[str]], mappings: Any) -> set[str]:
    return {
        key
        for mapping in mappings or []
        if isinstance(mapping, dict) and isinstance(mapping.get("inputs"), dict)
        for key, entry in mapping["inputs"].items()
        if isinstance(entry, dict)
        and json.dumps(entry.get("value"), default=str, sort_keys=True) in stored.get(str(key), set())
    }


def filled_secret_keys(secrets: dict) -> set[str]:
    # A blank optional secret holds nothing the code could send.
    return {key for key, entry in secrets.items() if entry.get("value") not in (None, "", {})}


def replaces_stored_value(value: Any, stored: Any) -> bool:
    """Whether a staged value keeps none of the stored one. A dictionary edited with some entries still masked
    keeps those entries, so it does not."""
    if value == stored:
        return False
    if isinstance(value, dict) and isinstance(stored, dict):
        return not any(key in stored and stored[key] == entry for key, entry in value.items())
    return True


# Fields the serializer computes from what the user saved. Each sits at a fixed place, never inside a value, so a
# value that holds a key with one of these names still counts.
_DERIVED_FIELDS = frozenset({"bytecode", "bytecode_contract", "bytecode_error", "input_deps", "order", "transpiled"})


def _without_derived_fields(entry: Any) -> Any:
    if not isinstance(entry, dict):
        return entry
    return {key: value for key, value in entry.items() if key not in _DERIVED_FIELDS}


def _authored_inputs(inputs: Any, secret_keys: set[str]) -> Any:
    if not isinstance(inputs, dict):
        return inputs
    return {str(key): _without_derived_fields(item) for key, item in inputs.items() if key not in secret_keys}


def _authored_mapping(mapping: Any) -> Any:
    if not isinstance(mapping, dict):
        return mapping
    return {
        **mapping,
        "inputs": _authored_inputs(mapping.get("inputs"), set()),
        "filters": _without_derived_fields(mapping.get("filters")),
    }


def guarded_content(hog: Optional[str], inputs: Any, inputs_schema: Any, mappings: Any, secret_keys: set[str]) -> str:
    """Everything the user saved that decides where the code sends a secret it reads, as canonical JSON. Any change
    to it counts, so no field can be missed. Derived values such as bytecode are left out, because the editor sends
    the whole config on every save and a recompile must not count as a change. Secret values are compared apart."""
    return json.dumps(
        {
            # The serializer trims the code it saves.
            "hog": (hog or "").strip(),
            "inputs_schema": inputs_schema or [],
            "inputs": _authored_inputs(inputs, secret_keys),
            "mappings": [_authored_mapping(mapping) for mapping in mappings or []],
        },
        default=str,
        sort_keys=True,
    )
