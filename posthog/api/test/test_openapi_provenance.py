from enum import StrEnum

from parameterized import parameterized
from pydantic import BaseModel

from posthog.schema import LogSeverityLevel, PropertyGroupFilter

from posthog.api.openapi_provenance import (
    SCHEMA_SOURCE_KEY,
    resolve_def_class,
    schema_source_path,
    tag_components_from_model,
)


class _LocalEnum(StrEnum):
    A = "a"
    B = "b"


class _LocalNested(BaseModel):
    flag: bool | None = None


class _Wrapper(BaseModel):
    group: PropertyGroupFilter | None = None
    level: LogSeverityLevel | None = None
    nested: _LocalNested | None = None
    choice: _LocalEnum | None = None


def _components_for(model: type[BaseModel]) -> dict[str, dict]:
    raw = model.model_json_schema(mode="serialization")
    defs = raw.pop("$defs", {})
    return {**defs, model.__name__: raw}


class TestOpenApiProvenance:
    def test_root_model_tagged_exactly(self):
        components = _components_for(_Wrapper)
        tag_components_from_model(components, _Wrapper)
        assert components["_Wrapper"][SCHEMA_SOURCE_KEY] == schema_source_path(_Wrapper)
        assert components["_Wrapper"][SCHEMA_SOURCE_KEY].endswith("test_openapi_provenance._Wrapper")

    @parameterized.expand(
        [
            ("kernel_model", "PropertyGroupFilter", "posthog.schema.PropertyGroupFilter"),
            ("kernel_enum", "LogSeverityLevel", "posthog.schema.LogSeverityLevel"),
        ]
    )
    def test_kernel_defs_tagged_with_posthog_schema(self, _name, def_name, expected):
        components = _components_for(_Wrapper)
        tag_components_from_model(components, _Wrapper)
        assert components[def_name][SCHEMA_SOURCE_KEY] == expected

    @parameterized.expand(
        [
            ("local_model", "_LocalNested"),
            ("local_enum", "_LocalEnum"),
        ]
    )
    def test_local_defs_resolved_via_root_module(self, _name, def_name):
        components = _components_for(_Wrapper)
        tag_components_from_model(components, _Wrapper)
        assert components[def_name][SCHEMA_SOURCE_KEY].startswith("posthog.api.test.test_openapi_provenance.")

    def test_structural_mismatch_yields_no_tag(self):
        wrong_shape = {"type": "object", "properties": {"definitely_not": {}, "the_same": {}}}
        assert resolve_def_class("PropertyGroupFilter", wrong_shape, _Wrapper) is None

    def test_unresolvable_name_yields_no_tag(self):
        schema = {"type": "object", "properties": {}}
        assert resolve_def_class("NoSuchClassAnywhere", schema, _Wrapper) is None
