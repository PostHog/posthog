"""How a template marks a connection input whose credential the worker applies, so the code never reads it.

Code passes the input to `fetch` as `{'auth': inputs.<key>}`. The worker takes where the credential goes and the
origins it may go to from the connection's kind, never from the schema, so a schema edit cannot move it. Secret
inputs carry no `auth`: a change to a function that holds one needs the secret typed again.
"""

from typing import Any

from django.db import models

from rest_framework import serializers


class AuthScheme(models.TextChoices):
    BEARER = "bearer", "bearer"
    HEADER = "header", "header"
    BASIC = "basic", "basic"
    QUERY = "query", "query"
    BODY = "body", "body"


def _validate_declaration(item: dict[str, Any]) -> None:
    if item.get("type") != "integration":
        raise serializers.ValidationError("auth can only be set on an integration input.")
    declaration = item.get("auth")
    if not isinstance(declaration, dict) or set(declaration) != {"scheme"}:
        raise serializers.ValidationError("auth takes only a scheme. The connection's kind sets the rest.")
    if declaration["scheme"] not in AuthScheme.values:
        raise serializers.ValidationError(f"auth.scheme must be one of: {', '.join(AuthScheme.values)}.")


def validate_auth_declarations(schemas: Any) -> None:
    if not isinstance(schemas, list):
        return
    errors = {}
    for item in schemas:
        if isinstance(item, dict) and "auth" in item:
            try:
                _validate_declaration(item)
            except serializers.ValidationError as error:
                errors[str(item.get("key"))] = error.detail
    if errors:
        raise serializers.ValidationError({"auth": errors})
