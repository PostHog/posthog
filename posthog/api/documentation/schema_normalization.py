"""OpenAPI 3.1 schema cleanup applied to component and operation schemas."""


def _strip_null_from_path_param(param: dict) -> dict:
    """Path parameters can never be ``null`` — they're URL segments. drf-spectacular
    propagates the underlying model field's ``null=True`` into the parameter schema,
    which in 3.1 surfaces as ``type: ["X", "null"]`` and makes generated TS clients
    accept ``null`` for required path IDs (e.g. ``insightId: number | null``).  Strip
    the null branch from any path-param schema so callers can't pass ``null`` and
    build URLs like ``/insights/null/sharing/``.
    """
    schema = param.get("schema")
    if not isinstance(schema, dict):
        return param

    # Common case: type-array form ``type: ["integer", "null"]`` → ``type: "integer"``
    schema_type = schema.get("type")
    if isinstance(schema_type, list) and "null" in schema_type:
        non_null = [t for t in schema_type if t != "null"]
        new_schema = dict(schema)
        new_schema["type"] = non_null[0] if len(non_null) == 1 else non_null
        return {**param, "schema": new_schema}

    # ``anyOf`` form: drop the null branch.
    if isinstance(schema.get("anyOf"), list):
        non_null = [s for s in schema["anyOf"] if not (isinstance(s, dict) and s.get("type") == "null")]
        if len(non_null) != len(schema["anyOf"]):
            new_schema = dict(schema)
            if len(non_null) == 1:
                # Single non-null branch — inline it, dropping the combinator.
                new_schema.pop("anyOf")
                new_schema.update(non_null[0])
            else:
                new_schema["anyOf"] = non_null
            return {**param, "schema": new_schema}

    return param


def _fix_pydantic_schema_for_openapi(schema):
    """
    Recursively clean up Pydantic v2 JSON Schema for OpenAPI 3.1.

    Pydantic v2 generates JSON Schema 2020-12, which is the base dialect for OpenAPI 3.1, so
    most constructs (``anyOf`` with ``{"type": "null"}``, ``const``, ``$ref`` siblings) are
    already valid and need no transformation. This function only handles the remaining edge
    cases:

    - ``additionalProperties: {}`` → ``true`` — an empty object schema means "any type" but
      trips vacuum's ``oas-missing-type`` rule since the inner object lacks a ``type`` key.
      Boolean ``true`` is the spec-blessed equivalent.
    - Collapses ``oneOf: [{}, {"type": "null"}]`` (and the ``anyOf`` variant) to just ``{}``
      — drf-spectacular's ``append_meta`` emits this for bare-nullable JSONFields in 3.1 mode
      (the equivalent of 3.0's ``nullable: true`` on a typeless schema). Empty ``{}`` already
      matches any value including ``null`` in JSON Schema, so the combinator is redundant —
      and Orval translates the verbose form to ``zod.union([zod.unknown(), zod.null()])``
      instead of the cleaner ``zod.unknown()``.
    - Strips vestigial numeric bounds (``minimum``/``maximum`` etc.) from schemas whose only
      content is ref-only combinators — drf-spectacular emits these for ``IntegerChoices``
      fields and nullable enums; the ref'd components already encode the allowed values so the
      bounds are redundant and vacuum flags them.
    - Collapses ``{"allOf": [{"$ref": "..."}]}`` to just the ``$ref`` — drf-spectacular's
      ``safe_ref()`` wraps refs in single-entry ``allOf`` for safety; once siblings are
      stripped the wrapping is unnecessary and vacuum's ``no-unnecessary-combinator`` flags it.
    - Converts any leftover ``"nullable": true`` to the 3.1 idiom. drf-spectacular runs this
      transform itself (in ``append_meta``) for schemas it builds from DRF fields, but it
      doesn't re-process schemas that come from external sources — DRF's
      ``get_paginated_response_schema()`` hard-codes ``nullable: true`` on its
      ``next``/``previous`` URLs, and hand-written ``@extend_schema_field`` annotations using
      the old 3.0 spelling slip through the same gap.  We normalise both here so vacuum's
      ``oas3-schema`` rule stops firing on the 3.1 spec.
    """
    if not isinstance(schema, dict):
        return schema

    schema = dict(schema)

    # Collapse the bare-nullable-any pattern drf-spectacular emits for nullable JSONFields:
    # {"oneOf": [{}, {"type": "null"}]} → {}.  Must run before the recursive walks below so
    # the cleanup also catches nested occurrences.
    for combinator in ("oneOf", "anyOf"):
        entries = schema.get(combinator)
        if entries == [{}, {"type": "null"}] or entries == [{"type": "null"}, {}]:
            schema.pop(combinator)

    # Normalise leftover ``"nullable": true`` to OpenAPI 3.1 form. Mirrors the conversion
    # drf-spectacular's ``append_meta`` performs for its own output; needed here because
    # DRF pagination and hand-written ``@extend_schema_field`` schemas bypass that path.
    if schema.pop("nullable", None) is True:
        if isinstance(schema.get("type"), str):
            schema["type"] = [schema["type"], "null"]
        elif isinstance(schema.get("type"), list):
            if "null" not in schema["type"]:
                schema["type"] = [*schema["type"], "null"]
        elif "$ref" in schema:
            ref = schema.pop("$ref")
            schema["oneOf"] = [{"$ref": ref}, {"type": "null"}]
        elif isinstance(schema.get("oneOf"), list):
            if not any(isinstance(e, dict) and e.get("type") == "null" for e in schema["oneOf"]):
                schema["oneOf"] = [*schema["oneOf"], {"type": "null"}]
        elif isinstance(schema.get("anyOf"), list):
            if not any(isinstance(e, dict) and e.get("type") == "null" for e in schema["anyOf"]):
                schema["anyOf"] = [*schema["anyOf"], {"type": "null"}]
        # Bare ``{"nullable": true}`` (no type, no combinator) means "any value or null", which
        # an empty schema already expresses — nothing to add.

    # Recursively fix nested schemas
    if "anyOf" in schema:
        schema["anyOf"] = [_fix_pydantic_schema_for_openapi(s) for s in schema["anyOf"]]

    if "properties" in schema:
        schema["properties"] = {k: _fix_pydantic_schema_for_openapi(v) for k, v in schema["properties"].items()}

    if "additionalProperties" in schema and isinstance(schema["additionalProperties"], dict):
        if schema["additionalProperties"] == {}:
            schema["additionalProperties"] = True
        else:
            schema["additionalProperties"] = _fix_pydantic_schema_for_openapi(schema["additionalProperties"])

    if "items" in schema:
        if isinstance(schema["items"], dict):
            schema["items"] = _fix_pydantic_schema_for_openapi(schema["items"])
        elif isinstance(schema["items"], list):
            schema["items"] = [_fix_pydantic_schema_for_openapi(s) for s in schema["items"]]

    if "allOf" in schema:
        schema["allOf"] = [_fix_pydantic_schema_for_openapi(s) for s in schema["allOf"]]

    if "oneOf" in schema:
        schema["oneOf"] = [_fix_pydantic_schema_for_openapi(s) for s in schema["oneOf"]]

    # Strip vestigial numeric bounds from ref-only combinator schemas (no ``type`` present).
    # The ref'd components already encode the allowed values; bounds here are meaningless.
    if "type" not in schema:
        ref_only_combinators = [
            schema[k]
            for k in ("allOf", "oneOf", "anyOf")
            if isinstance(schema.get(k), list) and all(isinstance(s, dict) and "$ref" in s for s in schema[k])
        ]
        if ref_only_combinators:
            for vestigial in ("minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum"):
                schema.pop(vestigial, None)

    # Collapse ``{"allOf": [{"$ref": "..."}]}`` to just the ``$ref``.
    if (
        list(schema.keys()) == ["allOf"]
        and isinstance(schema["allOf"], list)
        and len(schema["allOf"]) == 1
        and isinstance(schema["allOf"][0], dict)
    ):
        return schema["allOf"][0]

    return schema


def _unrequire_deprecated_dashboards_field(schema):
    """
    The deprecated insight `dashboards` field is gated behind an opt-in query parameter, so it
    can be absent from any insight payload — but drf-spectacular always marks read-only fields
    as required, which would make strict generated clients reject gated responses. Un-require
    it wherever it appears alongside its replacement, `dashboard_tiles`.
    """
    properties = schema.get("properties") if isinstance(schema, dict) else None
    if not isinstance(properties, dict) or not {"dashboards", "dashboard_tiles"} <= properties.keys():
        return schema
    required = schema.get("required")
    if isinstance(required, list) and "dashboards" in required:
        schema["required"] = [field for field in required if field != "dashboards"]
    return schema
