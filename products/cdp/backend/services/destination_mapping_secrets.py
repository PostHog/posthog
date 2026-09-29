"""Move secret mapping inputs into a destination's encrypted inputs.

Mappings have no encrypted column, so a secret mapping input stores its value in plain text.
The API now rejects secret mapping inputs, which also blocks every UI save of a destination
that still has one, because the UI resends the whole `mappings` list.

The executor builds each mapping's inputs as `{...inputs, ...encrypted_inputs, ...mapping.inputs}`.
A key that has one value across all mappings, and that the destination inputs do not already
use, can move to the destination inputs as a secret without changing what the destination sends.
Other keys are reported and left in place.
"""

import copy
import json
from typing import Any, Optional

from django.db import transaction

from posthog.dataclasses import frozen

from products.cdp.backend.models.hog_functions.hog_function import HogFunction


@frozen
class MappingSecretKey:
    team_id: int
    function_id: str
    key: str
    skip_reason: Optional[str] = None

    @property
    def movable(self) -> bool:
        return self.skip_reason is None


def _secret_mapping_keys(mappings: list[Any]) -> list[str]:
    keys: list[str] = []
    for mapping in mappings:
        for schema in (mapping or {}).get("inputs_schema") or []:
            if schema.get("secret") and schema.get("key") and schema["key"] not in keys:
                keys.append(schema["key"])
    return keys


def _stored_values(mappings: list[Any], key: str) -> list[Any]:
    return [
        (mapping.get("inputs") or {})[key]
        for mapping in mappings
        if isinstance(mapping, dict) and ((mapping.get("inputs") or {}).get(key) or {}).get("value") is not None
    ]


def _skip_reason(hog_function: HogFunction, key: str) -> Optional[str]:
    if any(schema.get("key") == key for schema in hog_function.inputs_schema or []):
        return "the destination inputs already use this key"
    values = {
        json.dumps(value.get("value"), sort_keys=True) for value in _stored_values(hog_function.mappings or [], key)
    }
    if len(values) > 1:
        return "mappings store different values for this key"
    return None


def find_mapping_secret_keys(team_id: Optional[int] = None) -> list[MappingSecretKey]:
    # Deleted destinations still hold the plain text value, so they stay in scope.
    queryset = HogFunction.objects.filter(mappings__contains=[{"inputs_schema": [{"secret": True}]}])
    if team_id is not None:
        queryset = queryset.filter(team_id=team_id)
    return [
        MappingSecretKey(
            team_id=hog_function.team_id,
            function_id=str(hog_function.id),
            key=key,
            skip_reason=_skip_reason(hog_function, key),
        )
        for hog_function in queryset.only("id", "team_id", "inputs_schema", "mappings")
        for key in _secret_mapping_keys(hog_function.mappings or [])
    ]


def _move_keys(hog_function: HogFunction, keys: list[str]) -> None:
    inputs_schema = list(hog_function.inputs_schema or [])
    inputs = dict(hog_function.inputs or {})
    mappings: list[Any] = copy.deepcopy(hog_function.mappings or [])
    for key in keys:
        schema = next(
            schema for mapping in mappings for schema in mapping.get("inputs_schema") or [] if schema.get("key") == key
        )
        inputs_schema.append(schema)
        values = _stored_values(mappings, key)
        if values:
            # `save` moves every secret key of `inputs` into `encrypted_inputs`.
            inputs[key] = values[0]
        for mapping in mappings:
            mapping["inputs_schema"] = [s for s in mapping.get("inputs_schema") or [] if s.get("key") != key]
            (mapping.get("inputs") or {}).pop(key, None)
    hog_function.inputs_schema = inputs_schema
    hog_function.inputs = inputs
    hog_function.mappings = mappings
    hog_function.save()


def move_mapping_secrets(keys: list[MappingSecretKey]) -> int:
    keys_by_function: dict[tuple[int, str], list[str]] = {}
    for secret_key in keys:
        if secret_key.movable:
            keys_by_function.setdefault((secret_key.team_id, secret_key.function_id), []).append(secret_key.key)
    for (team_id, function_id), function_keys in keys_by_function.items():
        with transaction.atomic():
            hog_function = HogFunction.objects.select_for_update().get(team_id=team_id, id=function_id)
            _move_keys(hog_function, function_keys)
    return len(keys_by_function)
