"""Decode Django ``JSONField`` values with orjson instead of the stdlib ``json`` module.

Postgres returns ``jsonb`` as raw text — Django registers a no-op psycopg loader
(``register_default_jsonb(..., loads=lambda x: x)``) so it can apply ``JSONField.decoder``
itself. Every jsonb read therefore parses in Python via ``JSONField.from_db_value``: scalar
columns once, and ``ArrayField(JSONField)`` once per element (psycopg splits the array in C,
each element still raw text). orjson parses that text ~2.5-3.6x faster than stdlib ``json``,
so swapping the parser at this one method claws back CPU across every model and product with
no schema, query, or per-field changes. Applied once from ``PostHogConfig.ready()``.
"""

import json

from django.db.models.fields.json import JSONField

import orjson

_patched = False


def _orjson_from_db_value(self, value, expression, connection):
    if value is None:
        return value
    # A non-text value means the driver/backend already produced a native Python type
    # (KeyTransform on a scalar, SQLite, or a driver that deserializes jsonb itself —
    # Django #36371). Hand it back as-is rather than trying to parse it again.
    if not isinstance(value, (str, bytes, bytearray)):
        return value
    # orjson can't accept a custom json.JSONDecoder, so honor that field opt-out with stdlib.
    if self.decoder is not None:
        try:
            return json.loads(value, cls=self.decoder)
        except json.JSONDecodeError:
            return value
    try:
        return orjson.loads(value)
    except orjson.JSONDecodeError:
        return value


def apply() -> None:
    """Route JSONField decode through orjson. Idempotent; safe to call more than once."""
    global _patched
    if _patched:
        return
    # setattr (not direct assignment) keeps mypy/ty from flagging the method swap;
    # B010 would "fix" it back to a direct assignment, which reintroduces that error.
    setattr(JSONField, "from_db_value", _orjson_from_db_value)  # noqa: B010
    _patched = True
