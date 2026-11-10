"""Secrets a function's code still reads as raw values, and the saves that must carry them typed again.

A secret stored with a bound `auth` declaration reaches the code only as a credential handle, and the worker sets it on
requests to the bound origins. Any other stored secret is a legacy secret: the code reads its value, so a change to
the code, the inputs or the mappings could send it anywhere. Such a change must carry every legacy secret typed again.
"""

import json
from enum import StrEnum
from typing import Any, Optional

from rest_framework import serializers

from products.cdp.backend.credential_auth import bind_secret_auth
from products.cdp.backend.models.hog_function_template import HogFunctionTemplate

ANY_ORIGIN = "*"


class SecretReentry(StrEnum):
    REENTERED = "reentered"
    REFUSED = "refused"
    WOULD_REFUSE = "would_refuse"
    STAGED = "staged"


def has_bound_auth(entry: Any) -> bool:
    """The worker's test for a secret it applies itself, so this side and the worker agree on what is legacy."""
    auth = entry.get("auth") if isinstance(entry, dict) else None
    return isinstance(auth, dict) and isinstance(auth.get("scheme"), str) and isinstance(auth.get("origins"), list)


def stored_secrets(inputs: Optional[dict], inputs_schema: Optional[list], encrypted_inputs: Optional[dict]) -> dict:
    """Every secret the worker resolves for a stored function. A secret saved before inputs were encrypted is still
    in plaintext `inputs`, and the worker merges both columns by name."""
    plaintext = inputs or {}
    secret_keys = {
        schema.get("key") for schema in inputs_schema or [] if isinstance(schema, dict) and schema.get("secret")
    }
    return {
        **{key: entry for key, entry in plaintext.items() if key in secret_keys and isinstance(entry, dict)},
        **{key: entry for key, entry in (encrypted_inputs or {}).items() if isinstance(entry, dict)},
    }


def legacy_secret_keys(secrets: dict) -> set[str]:
    return {key for key, entry in secrets.items() if not has_bound_auth(entry)}


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
    # The worker reads the type to coerce a value and the templating flag to decide whether to render it.
    return {
        str(schema.get("key")): (schema.get("type"), bool(schema.get("secret")), _templating(schema.get("templating")))
        for schema in inputs_schema or []
        if isinstance(schema, dict)
    }


def _inputs_signature(inputs: Any, inputs_schema: Any, skipped: set[str]) -> dict:
    # Only inputs the schema declares are validated and kept, so an undeclared stored one is left out on both sides.
    # Values compare as JSON text because Python equates `True` with `1`, which the worker prints differently. Key
    # order counts because code can read it. The editor sends back the order the API returned.
    declared = _schema_signature(inputs_schema).keys() - skipped
    return {
        key: (json.dumps(item.get("value"), default=str), item.get("templating") == "liquid")
        for key, item in (inputs or {}).items()
        if isinstance(item, dict) and key in declared
    }


def guarded_content(hog: Optional[str], inputs: Any, inputs_schema: Any, mappings: Any, secret_keys: set[str]) -> tuple:
    """What decides where the code sends a secret it reads. Derived values such as bytecode are left out, because the
    editor sends the whole config on every save and a recompile must not count as a change."""
    return (
        hog or "",
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


def template_origins(template: Optional[HogFunctionTemplate], key: str, inputs: dict) -> str | list[str]:
    """The origins the template declares for a secret, or any origin when it declares none. Code is never read."""
    declaration = next(
        (
            schema.get("auth")
            for schema in (template.inputs_schema if template else None) or []
            if isinstance(schema, dict) and schema.get("key") == key and schema.get("secret")
        ),
        None,
    )
    if not isinstance(declaration, dict):
        return ANY_ORIGIN
    try:
        return sorted(bind_secret_auth(declaration, inputs)["origins"])
    except (serializers.ValidationError, KeyError, TypeError):
        return ANY_ORIGIN
