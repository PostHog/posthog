import typing
import dataclasses
from collections.abc import Iterable
from typing import Any, ClassVar

from django.core.exceptions import ImproperlyConfigured
from django.utils.functional import cached_property

from drf_spectacular.openapi import AutoSchema
from drf_spectacular.utils import Direction
from rest_framework import serializers
from rest_framework_dataclasses.field_utils import DataclassDefinition, TypeInfo, get_dataclass_definition
from rest_framework_dataclasses.serializers import DataclassSerializer, KWArgs, SerializerFieldDefinition

from posthog.api.documentation import LabeledEnumDataclassSerializerExtension


def _substitute_type_variables(field_type: Any, arguments: dict[Any, Any]) -> Any:
    if isinstance(field_type, typing.TypeVar):
        return arguments.get(field_type, field_type)
    parameters = getattr(field_type, "__parameters__", ())
    if parameters and not isinstance(field_type, type):
        return field_type[tuple(arguments.get(parameter, parameter) for parameter in parameters)]
    return field_type


# Do not give this class a docstring. drf-spectacular describes a component with the nearest
# docstring in the serializer's MRO, so a docstring here becomes the published description of
# every subclass that has none of its own.
class ContractResponseSerializer(DataclassSerializer[Any]):
    _serializers_by_dataclass: ClassVar[dict[Any, type["ContractResponseSerializer"]]] = {}

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Register the contract's serializer. A second one would make a nested component depend on import order."""
        super().__init_subclass__(**kwargs)
        meta = cls.__dict__.get("Meta")
        dataclass_type = getattr(meta, "dataclass", None)
        if dataclass_type is None:
            return
        registered = ContractResponseSerializer._serializers_by_dataclass.get(dataclass_type)
        if registered is not None and (registered.__module__, registered.__qualname__) != (
            cls.__module__,
            cls.__qualname__,
        ):
            raise ImproperlyConfigured(
                f"{cls.__qualname__} and {registered.__qualname__} both render {dataclass_type}."
            )
        ContractResponseSerializer._serializers_by_dataclass[dataclass_type] = cls

    @cached_property
    def dataclass_definition(self) -> DataclassDefinition[Any]:
        """Put a generic contract's type arguments in place of its type variables, which the library reads as bounds."""
        dataclass_type = getattr(getattr(self, "Meta", None), "dataclass", None)
        origin = typing.get_origin(dataclass_type)
        if dataclass_type is None or origin is None:
            return super().dataclass_definition
        definition = get_dataclass_definition(origin)
        arguments = dict(zip(origin.__parameters__, typing.get_args(dataclass_type)))
        field_types = {
            name: _substitute_type_variables(field_type, arguments)
            for name, field_type in definition.field_types.items()
        }
        return DataclassDefinition(dataclass_type, definition.fields, field_types)

    def get_default_field_names(self, declared_fields: Iterable[str]) -> list[str]:
        """Keep the contract's field order, the schema and response order. The library puts declared fields first."""
        contract_fields = list(self.dataclass_definition.fields)
        return contract_fields + [name for name in declared_fields if name not in self.dataclass_definition.fields]

    def get_fields(self) -> dict[str, serializers.Field]:
        """Give each declared field the contract's help text, so a declared field only picks a field class."""
        fields = super().get_fields()
        for name in self._declared_fields:
            contract_field = self.dataclass_definition.fields.get(name)
            help_text = (
                contract_field.metadata.get("serializer_kwargs", {}).get("help_text") if contract_field else None
            )
            if help_text is None:
                continue
            if fields[name].help_text is not None:
                raise ImproperlyConfigured(
                    f"{type(self).__qualname__}.{name} sets help_text, which the contract field already documents."
                )
            fields[name].help_text = help_text
        return fields

    def build_typed_field(
        self, field_name: str, type_info: TypeInfo, extra_kwargs: KWArgs
    ) -> SerializerFieldDefinition:
        """Keep a field with a dataclass default required: a response renders every field. Wrong for a request body."""
        field_class, field_kwargs = super().build_typed_field(field_name, type_info, extra_kwargs)
        field_kwargs.pop("required", None)
        return field_class, field_kwargs

    def build_dataclass_field(self, field_name: str, type_info: TypeInfo) -> SerializerFieldDefinition:
        return self._serializer_for(type_info.base_type), {}

    def build_standard_field(self, field_name: str, type_info: TypeInfo) -> SerializerFieldDefinition:
        """Resolve a parameterized generic contract, which the library sends here because it is not a class."""
        if dataclasses.is_dataclass(typing.get_origin(type_info.base_type)):
            return self._serializer_for(type_info.base_type), {}
        return super().build_standard_field(field_name, type_info)

    @staticmethod
    def _serializer_for(dataclass_type: Any) -> type["ContractResponseSerializer"]:
        """Find a nested contract's serializer. The library's fallback would name the component after the dataclass."""
        serializer_class = ContractResponseSerializer._serializers_by_dataclass.get(dataclass_type)
        if serializer_class is None:
            raise ImproperlyConfigured(f"No ContractResponseSerializer renders {dataclass_type}.")
        return serializer_class


class ContractResponseSerializerExtension(LabeledEnumDataclassSerializerExtension):
    target_class = "posthog.api.contract_serializer.ContractResponseSerializer"
    priority = 2

    def get_name(self, *args: Any, **kwargs: Any) -> str | None:
        """None names the component after the serializer class, as for a hand-written serializer."""
        return None

    def get_identity(self, auto_schema: AutoSchema, direction: Direction) -> Any:
        """None identifies the component by its serializer, so two serializers sharing a name still get a warning."""
        return None
