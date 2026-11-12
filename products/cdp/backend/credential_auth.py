"""How a template marks a connection input whose credential the worker applies, so the code never reads it.

Code passes the input to `fetch` as `{'auth': inputs.<key>}`. The worker takes where the credential goes and the
origins it may go to from the connection's kind, so `auth` is only a marker and a schema edit cannot move the
credential. Secret inputs carry no `auth`: a change to a function that holds one needs the secret typed again.
"""

from typing import Any

from rest_framework import serializers


def _declaration_error(item: dict[str, Any]) -> str | None:
    if not isinstance(item["auth"], bool):
        return "auth must be true or false."
    if item["auth"] and item.get("type") != "integration":
        return "auth can only be set on an integration input."
    return None


def validate_auth_declarations(schemas: Any) -> None:
    if not isinstance(schemas, list):
        return
    errors = {
        str(item.get("key")): error
        for item in schemas
        if isinstance(item, dict) and "auth" in item and (error := _declaration_error(item))
    }
    if errors:
        raise serializers.ValidationError({"auth": errors})
