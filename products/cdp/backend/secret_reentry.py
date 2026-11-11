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


def _templating(value: Any) -> Optional[str]:
    if value is False:
        return None
    return "liquid" if value == "liquid" else "hog"


def _schema_signature(inputs_schema: Any) -> dict:
    # The worker reads the type to coerce a value and the templating flag to decide whether to render it. Validation
    # fills an empty required input with its default, which can give an empty secret input a value nobody typed.
    return {
        str(schema.get("key")): (
            schema.get("type"),
            bool(schema.get("secret")),
            _templating(schema.get("templating")),
            json.dumps(schema.get("default") if schema.get("required") else None, default=str, sort_keys=True),
        )
        for schema in inputs_schema or []
        if isinstance(schema, dict)
    }


def _inputs_signature(inputs: Any, inputs_schema: Any, skipped: set[str]) -> dict:
    # Only inputs the schema declares are validated and kept, so an undeclared stored one is left out on both sides.
    items = dict(inputs) if isinstance(inputs, dict) else {}
    for schema in inputs_schema or []:
        # Validation fills in the default of a missing required input, so a function stored without it compares
        # as if it held the default.
        if isinstance(schema, dict) and schema.get("required") and schema.get("default") is not None:
            if not items.get(schema.get("key")):
                items[str(schema["key"])] = {
                    "value": schema["default"],
                    "templating": _templating(schema.get("templating")),
                }
    schema_templating = {
        str(schema.get("key")): schema["templating"]
        for schema in inputs_schema or []
        if isinstance(schema, dict) and "templating" in schema
    }
    declared = _schema_signature(inputs_schema).keys() - skipped
    # Values compare as JSON text because Python equates `True` with `1`, which the worker prints differently. Keys
    # are sorted because Postgres `jsonb` stores object keys in its own order, so the worker never sees the order a
    # client sent.
    return {
        key: (
            json.dumps(item.get("value"), default=str, sort_keys=True),
            schema_templating.get(key, item.get("templating")) == "liquid",
        )
        for key, item in items.items()
        if isinstance(item, dict) and key in declared
    }


def guarded_content(hog: Optional[str], inputs: Any, inputs_schema: Any, mappings: Any, secret_keys: set[str]) -> tuple:
    """What decides where the code sends a secret it reads. Derived values such as bytecode are left out, because the
    editor sends the whole config on every save and a recompile must not count as a change."""
    return (
        # The serializer trims the code it saves.
        (hog or "").strip(),
        _schema_signature(inputs_schema),
        _inputs_signature(inputs, inputs_schema, secret_keys),
        [
            (
                _schema_signature(mapping.get("inputs_schema")),
                _inputs_signature(mapping.get("inputs"), mapping.get("inputs_schema"), set()),
            )
            for mapping in mappings or []
            if isinstance(mapping, dict)
        ],
    )
