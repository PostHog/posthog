from __future__ import annotations

from copy import deepcopy
from typing import Any

from drf_spectacular.drainage import warn as spectacular_warn
from drf_spectacular.utils import extend_schema_field, extend_schema_serializer
from pydantic import BaseModel
from rest_framework import serializers

from products.dashboards.backend.widget_specs.common import WidgetFilterEntry
from products.dashboards.backend.widget_specs.registry import WIDGET_SPECS

_OPENAPI_REF_PREFIX = "#/components/schemas/"

_STUB_SERIALIZER_CACHE: dict[type[BaseModel], type[serializers.Serializer]] = {}
_CONFIG_FIELD_CACHE: dict[type[BaseModel], type[serializers.JSONField]] = {}


def _rewrite_pydantic_refs(schema: Any, *, def_names: set[str]) -> Any:
    if isinstance(schema, dict):
        rewritten: dict[str, Any] = {}
        for key, value in schema.items():
            if key == "$ref" and isinstance(value, str) and value.startswith("#/$defs/"):
                def_name = value.removeprefix("#/$defs/")
                if def_name in def_names:
                    rewritten[key] = f"{_OPENAPI_REF_PREFIX}{def_name}"
                else:
                    rewritten[key] = value
            else:
                rewritten[key] = _rewrite_pydantic_refs(value, def_names=def_names)
        return rewritten
    if isinstance(schema, list):
        return [_rewrite_pydantic_refs(item, def_names=def_names) for item in schema]
    return schema


def pydantic_model_to_openapi_components(model: type[BaseModel]) -> dict[str, dict[str, Any]]:
    """Hoist Pydantic ``$defs`` into named OpenAPI component schemas."""
    raw_schema = model.model_json_schema(mode="serialization")
    defs = raw_schema.pop("$defs", {})
    def_names = set(defs.keys())

    components: dict[str, dict[str, Any]] = {}
    for def_name, def_schema in defs.items():
        cleaned = deepcopy(def_schema)
        cleaned.pop("$defs", None)
        components[def_name] = _rewrite_pydantic_refs(cleaned, def_names=def_names)

    root_schema = deepcopy(raw_schema)
    root_schema.pop("$defs", None)
    components[model.__name__] = _rewrite_pydantic_refs(root_schema, def_names=def_names)
    return components


def pydantic_openapi_ref(model: type[BaseModel]) -> dict[str, str]:
    return {"$ref": f"{_OPENAPI_REF_PREFIX}{model.__name__}"}


def pydantic_stub_serializer(model: type[BaseModel]) -> type[serializers.Serializer]:
    """Empty serializer shell — schema content is injected from Pydantic in postprocessing."""
    cached = _STUB_SERIALIZER_CACHE.get(model)
    if cached is not None:
        return cached

    component_name = model.__name__

    @extend_schema_serializer(component_name=component_name)
    class _StubSerializer(serializers.Serializer):
        pass

    _StubSerializer.__name__ = f"{component_name}OpenApiSerializer"
    _StubSerializer.__qualname__ = _StubSerializer.__name__
    _STUB_SERIALIZER_CACHE[model] = _StubSerializer
    return _StubSerializer


def pydantic_config_field(model: type[BaseModel], **kwargs: Any) -> serializers.JSONField:
    """JSONField whose OpenAPI shape is a ``$ref`` to the Pydantic-backed component."""
    cached = _CONFIG_FIELD_CACHE.get(model)
    if cached is None:

        @extend_schema_field(pydantic_openapi_ref(model))
        class _ConfigField(serializers.JSONField):
            pass

        _CONFIG_FIELD_CACHE[model] = _ConfigField

    return _CONFIG_FIELD_CACHE[model](**kwargs)


def inject_widget_spec_pydantic_components(
    result: dict[str, Any],
    generator: Any,
    request: Any,
    public: bool,
) -> dict[str, Any]:
    """POSTPROCESSING_HOOKS entry — inject Pydantic ``model_json_schema()`` widget components."""
    _ = (generator, request, public)
    from posthog.api.documentation import _fix_pydantic_schema_for_openapi

    schemas = result.setdefault("components", {}).setdefault("schemas", {})

    models_to_inject: list[type[BaseModel]] = [WidgetFilterEntry]
    for spec in WIDGET_SPECS.values():
        models_to_inject.append(spec.config_model)

    injected_names: set[str] = set()
    for model in models_to_inject:
        for component_name, component_schema in pydantic_model_to_openapi_components(model).items():
            if component_name in injected_names:
                continue
            injected_names.add(component_name)
            fixed_schema = _fix_pydantic_schema_for_openapi(component_schema)
            existing = schemas.get(component_name)
            if existing is not None and existing != fixed_schema:
                # e.g. PropertyOperator is also emitted by the /query Pydantic schema path and is
                # referenced by many unrelated components — never silently rewrite a divergent copy.
                # spectacular_warn flows into GENERATOR_STATS, so --fail-on-warn breaks the build.
                spectacular_warn(
                    f"Widget spec injection would overwrite component {component_name!r} with a different "
                    "schema. Rename the Pydantic model or reconcile the definitions."
                )
                continue
            schemas[component_name] = fixed_schema

    # PolymorphicProxySerializer shells for per-type config have no DRF fields, so spectacular
    # emits oneOf: []. Orval 8.14+ turns that into an invalid empty TS union.
    config_refs = [{"$ref": f"{_OPENAPI_REF_PREFIX}{spec.config_model.__name__}"} for spec in WIDGET_SPECS.values()]
    if config_refs:
        schemas["DashboardWidgetConfig"] = {"oneOf": config_refs}

    return result
