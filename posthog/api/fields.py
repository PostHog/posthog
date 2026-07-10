"""Reusable DRF serializer fields shared across the API.

Add generic, endpoint-agnostic serializer field types here so viewsets can
reuse them instead of redefining local copies.
"""

import json

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers


class OptionalBooleanField(serializers.BooleanField):
    """BooleanField that returns None when missing instead of False."""

    default_empty_html = None

    def __init__(self, **kwargs):
        kwargs.setdefault("allow_null", True)
        super().__init__(**kwargs)


@extend_schema_field({"type": "string"})
class JSONStringFilterField(serializers.JSONField):
    """JSONField exposed as a JSON-encoded string in the schema (for query string clients)."""

    pass


class JSONTolerantListField(serializers.ListField):
    """ListField that also accepts a single JSON-encoded array as the query value.

    Standard clients send array query params as repeated params
    (?scopes=a&scopes=b), which DRF reads via ``getlist``. Some clients (e.g. the
    MCP client) send a single JSON-encoded array instead (?scopes=["a","b"]);
    accept that too so both encodings resolve to the same filter.
    """

    def get_value(self, dictionary):
        value = super().get_value(dictionary)
        if isinstance(value, list) and len(value) == 1 and isinstance(value[0], str):
            candidate = value[0].strip()
            if candidate.startswith("[") and candidate.endswith("]"):
                try:
                    parsed = json.loads(candidate)
                except (json.JSONDecodeError, ValueError):
                    return value
                if isinstance(parsed, list):
                    return parsed
        return value
