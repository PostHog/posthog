from __future__ import annotations

import copy
from collections.abc import Iterable, Mapping
from dataclasses import MISSING, fields
from functools import cache
from types import MappingProxyType
from typing import Any

from pydantic import BaseModel, TypeAdapter
from pydantic_core import PydanticUndefined


class SchemaFieldInfo:
    """Lightweight stand-in for pydantic.fields.FieldInfo."""

    __slots__ = ("annotation", "default", "default_factory")

    def __init__(self, annotation: Any, default: Any = PydanticUndefined, default_factory: Any = PydanticUndefined):
        self.annotation = annotation
        self.default = default
        self.default_factory = default_factory


@cache
def _type_adapter(cls: type[Any]) -> TypeAdapter[Any]:
    return TypeAdapter(cls)


@cache
def _model_fields(cls: type[Any]) -> Mapping[str, SchemaFieldInfo]:
    field_map: dict[str, SchemaFieldInfo] = {}
    for field in fields(cls):
        default = field.default if field.default is not MISSING else PydanticUndefined
        default_factory = field.default_factory if field.default_factory is not MISSING else PydanticUndefined
        field_map[field.name] = SchemaFieldInfo(
            annotation=field.type,
            default=default,
            default_factory=default_factory,
        )
    return MappingProxyType(field_map)


def _default_value(info: SchemaFieldInfo) -> Any:
    if info.default is not PydanticUndefined:
        return info.default
    if info.default_factory is not PydanticUndefined:
        return info.default_factory()
    return PydanticUndefined


class _ModelFieldsDescriptor:
    def __get__(self, instance: Any, owner: type[Any]) -> Mapping[str, SchemaFieldInfo]:
        return _model_fields(owner if owner is not None else type(instance))


class SchemaModel:
    """Compatibility mixin that adds the pydantic BaseModel API to dataclasses."""

    __slots__ = ()

    model_fields = _ModelFieldsDescriptor()

    @property
    def model_fields_set(self) -> set[str]:
        result: set[str] = set()
        for name, info in type(self).model_fields.items():
            value = getattr(self, name)
            default_value = _default_value(info)
            if default_value is PydanticUndefined:
                if value is not None:
                    result.add(name)
            elif value != default_value:
                result.add(name)
        return result

    @classmethod
    def model_validate(cls, data: Any, *args: Any, **kwargs: Any):
        return _type_adapter(cls).validate_python(data, *args, **kwargs)

    @classmethod
    def model_validate_json(cls, data: str | bytes, *args: Any, **kwargs: Any):
        return _type_adapter(cls).validate_json(data, *args, **kwargs)

    @classmethod
    def model_json_schema(cls, *args: Any, **kwargs: Any) -> Mapping[str, Any]:
        return _type_adapter(cls).json_schema(*args, **kwargs)

    def model_dump(self, *args: Any, **kwargs: Any) -> Any:
        return _type_adapter(type(self)).dump_python(self, *args, **kwargs)

    def model_dump_json(self, *args: Any, **kwargs: Any) -> str:
        return _type_adapter(type(self)).dump_json(self, *args, **kwargs).decode()

    def dict(self, *args: Any, **kwargs: Any) -> Any:
        return self.model_dump(*args, **kwargs)

    def json(self, *args: Any, **kwargs: Any) -> str:
        return self.model_dump_json(*args, **kwargs)

    @classmethod
    def model_construct(cls, _fields_set: Iterable[str] | None = None, **values: Any):
        return cls(**values)

    def model_copy(self, *, update: Mapping[str, Any] | None = None, deep: bool = False):
        data = self.model_dump()
        if update:
            data.update(update)
        if deep:
            data = copy.deepcopy(data)
        return type(self)(**data)


SCHEMA_MODEL_TYPES: tuple[type[Any], ...] = (BaseModel, SchemaModel)


def is_schema_model(value: Any) -> bool:
    return isinstance(value, SCHEMA_MODEL_TYPES)
