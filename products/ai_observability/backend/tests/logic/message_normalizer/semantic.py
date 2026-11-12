import json

from products.ai_observability.backend.logic.message_normalizer.values import JsonValue


def canonical(value: JsonValue) -> JsonValue:
    # The Python engine must match the TypeScript one by meaning, not bytes: a null field equals a missing one,
    # numbers compare by value, and JSON inside a string compares by its parsed value. Booleans become marker strings
    # because Python treats `True == 1` as equal and JavaScript does not.
    if isinstance(value, bool):
        return "<true>" if value else "<false>"
    if isinstance(value, str):
        return _canonical_text(value)
    if isinstance(value, dict):
        return {key: canonical(item) for key, item in value.items() if item is not None}
    if isinstance(value, list):
        return [canonical(item) for item in value]
    return value


def _canonical_text(text: str) -> JsonValue:
    stripped = text.strip()
    if not stripped.startswith(("{", "[")):
        return text
    try:
        return {"<json>": canonical(json.loads(stripped))}
    except ValueError:
        return text
