"""Postprocessing hook that warns about self-inconsistent schemas."""

import re
from typing import Any

from drf_spectacular.drainage import warn as spectacular_warn

_OPERATION_ID_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

_HTTP_METHODS = frozenset({"get", "put", "post", "delete", "options", "head", "patch", "trace"})


def lint_spec_consistency_hook(result, generator, request, public):
    """Postprocessing hook that emits drf-spectacular warnings for spec self-inconsistencies.

    Runs as a regular postprocessing hook so the warnings flow through ``GENERATOR_STATS``
    and are picked up by ``--fail-on-warn`` in CI. Catches the kind of bug where the spec
    is internally syntactically valid but logically contradictory — e.g. a field declares
    ``default="days"`` while its ``enum`` lists ``["DAY", ...]``. drf-spectacular itself
    doesn't cross-validate these, and DRF doesn't either, so the inconsistency silently
    propagates into the generated TypeScript / MCP definitions until something downstream
    chokes on it.

    Currently checks:

    * ``default`` is a member of ``enum`` (when both are present, including across
      ``$ref`` and ``allOf`` — the enum often lives in the referenced component).
    * Every name in ``required`` is declared in ``properties`` — but only on flat
      object schemas. Skipped when combinators (``allOf``/``oneOf``/``anyOf``) are
      present, since composed schemas can satisfy ``required`` from a referenced
      branch and a flat check would false-positive.
    """

    components_schemas = (result.get("components") or {}).get("schemas") or {}

    def resolve_ref(ref: str) -> dict[str, Any] | None:
        if not isinstance(ref, str) or not ref.startswith("#/components/schemas/"):
            return None
        return components_schemas.get(ref.replace("#/components/schemas/", ""))

    def collect_enum(node: Any, seen: set[int] | None = None) -> list[Any] | None:
        """Walk ``$ref`` and ``allOf`` branches looking for an ``enum``. Returns the first
        enum found (refs and allOf branches in nested schemas almost always share the
        same enum) or None. ``seen`` guards against cycles.
        """
        if not isinstance(node, dict):
            return None
        node_id = id(node)
        if seen is None:
            seen = set()
        if node_id in seen:
            return None
        seen.add(node_id)
        if isinstance(node.get("enum"), list):
            return node["enum"]
        if isinstance(node.get("$ref"), str):
            target = resolve_ref(node["$ref"])
            if target is not None:
                found = collect_enum(target, seen)
                if found is not None:
                    return found
        if isinstance(node.get("allOf"), list):
            for branch in node["allOf"]:
                found = collect_enum(branch, seen)
                if found is not None:
                    return found
        return None

    def emit(message: str, location: str) -> None:
        spectacular_warn(f"spec consistency: {message} at {location}")

    def is_effectively_nullable(node: dict[str, Any]) -> bool:
        """``default: null`` is fine on a nullable schema even if ``null`` isn't in the enum.

        In OpenAPI 3.1 a schema is nullable when it uses ``type: ["X", "null"]``,
        ``oneOf/anyOf: [..., {"type": "null"}]``, or ``oneOf: [..., NullEnum]`` (the
        component drf-spectacular emits for explicit null enum members). All three forms
        should suppress the ``default`` membership check.
        """
        type_field = node.get("type")
        if isinstance(type_field, list) and "null" in type_field:
            return True
        for combinator in ("oneOf", "anyOf"):
            entries = node.get(combinator)
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                ref = entry.get("$ref")
                if isinstance(ref, str) and ref.endswith("NullEnum"):
                    return True
                if entry.get("type") == "null":
                    return True
        return False

    def walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            if "default" in node:
                # Look for enum locally, then through $ref/allOf — drf-spectacular's
                # enum components sit behind a ref-or-allOf wrapper for nullable enums.
                enum_values = collect_enum(node)
                if enum_values is not None and node["default"] not in enum_values:
                    if not (node["default"] is None and is_effectively_nullable(node)):
                        emit(
                            f"default={node['default']!r} is not a member of enum={enum_values!r}",
                            path,
                        )
            if isinstance(node.get("required"), list) and isinstance(node.get("properties"), dict):
                # Only check on flat object schemas. If the schema also uses allOf/oneOf/anyOf
                # the required field may be satisfied by a referenced branch; a flat lookup
                # would emit a false positive.
                if not any(k in node for k in ("allOf", "oneOf", "anyOf")):
                    missing = [r for r in node["required"] if r not in node["properties"]]
                    if missing:
                        emit(f"required field(s) {missing!r} not declared in properties", path)
            for k, v in node.items():
                walk(v, f"{path}.{k}")
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{path}[{i}]")

    walk(result, "$")

    # operationId must be a valid identifier — drf-spectacular auto-derives it from the
    # URL path, so segments like `@me` produce `..._@me_..._list` which (a) breaks the
    # MCP YAML scaffolder, whose keys can't contain `@`, and (b) is rejected by any
    # OpenAPI-typed-client codegen that maps it to a function name. The fix is to set
    # `operation_id="..."` explicitly on `@extend_schema` — surface it here so CI catches
    # it the same day it lands instead of breaking the MCP build downstream.
    paths = result.get("paths") or {}
    for url_path, methods in paths.items():
        if not isinstance(methods, dict):
            continue
        for method, op in methods.items():
            if method not in _HTTP_METHODS or not isinstance(op, dict):
                continue
            op_id = op.get("operationId")
            if isinstance(op_id, str) and not _OPERATION_ID_RE.match(op_id):
                spectacular_warn(
                    f"spec consistency: operationId {op_id!r} contains non-identifier "
                    f"characters (must match {_OPERATION_ID_RE.pattern}) at "
                    f"{method.upper()} {url_path}. Set `operation_id=` explicitly on "
                    f"`@extend_schema(...)` to override the URL-derived default."
                )

    return result
