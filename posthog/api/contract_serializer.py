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
            # A nested contract finds its serializer by its type, so two serializers for one type
            # would make the schema component depend on import order.
            raise ImproperlyConfigured(
                f"{cls.__qualname__} and {registered.__qualname__} both render {dataclass_type}."
            )
        ContractResponseSerializer._serializers_by_dataclass[dataclass_type] = cls

    @cached_property
    def dataclass_definition(self) -> DataclassDefinition[Any]:
        dataclass_type = getattr(getattr(self, "Meta", None), "dataclass", None)
        origin = typing.get_origin(dataclass_type)
        if dataclass_type is None or origin is None:
            return super().dataclass_definition
        # rest_framework_dataclasses reads a type variable as its bound, so a `Section[Payload]`
        # would render the payload field as the bound and not as `Payload`. Put the type arguments
        # in place of the type variables.
        definition = get_dataclass_definition(origin)
        arguments = dict(zip(origin.__parameters__, typing.get_args(dataclass_type)))
        field_types = {
            name: _substitute_type_variables(field_type, arguments)
            for name, field_type in definition.field_types.items()
        }
        return DataclassDefinition(dataclass_type, definition.fields, field_types)

    def get_default_field_names(self, declared_fields: Iterable[str]) -> list[str]:
        # The library puts declared fields first. Keep the contract's order, because it sets the
        # order of the schema properties and of the keys in the response.
        contract_fields = list(self.dataclass_definition.fields)
        return contract_fields + [name for name in declared_fields if name not in self.dataclass_definition.fields]

    def get_fields(self) -> dict[str, serializers.Field]:
        fields = super().get_fields()
        # A field declared on the serializer only picks a field class. Its documentation stays on
        # the contract, so a response field is documented in one place.
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
        field_class, field_kwargs = super().build_typed_field(field_name, type_info, extra_kwargs)
        # The library makes a field with a dataclass default optional. A response renders every
        # field of the instance, so the field stays required in the schema. This is the rule that
        # makes the class wrong for a request body.
        field_kwargs.pop("required", None)
        return field_class, field_kwargs

    def build_dataclass_field(self, field_name: str, type_info: TypeInfo) -> SerializerFieldDefinition:
        return self._serializer_for(type_info.base_type), {}

    def build_standard_field(self, field_name: str, type_info: TypeInfo) -> SerializerFieldDefinition:
        # A parameterized generic contract is not a class, so the library sends it here and not to
        # build_dataclass_field.
        if dataclasses.is_dataclass(typing.get_origin(type_info.base_type)):
            return self._serializer_for(type_info.base_type), {}
        return super().build_standard_field(field_name, type_info)

    @staticmethod
    def _serializer_for(dataclass_type: Any) -> type["ContractResponseSerializer"]:
        serializer_class = ContractResponseSerializer._serializers_by_dataclass.get(dataclass_type)
        if serializer_class is None:
            # The library would nest an anonymous serializer, which drf-spectacular names after the
            # dataclass. Refuse it, so every component keeps the name of a serializer class.
            raise ImproperlyConfigured(f"No ContractResponseSerializer renders {dataclass_type}.")
        return serializer_class


class ContractResponseSerializerExtension(LabeledEnumDataclassSerializerExtension):
    target_class = "posthog.api.contract_serializer.ContractResponseSerializer"
    priority = 2

    # drf-spectacular's two base classes declare get_name with different signatures, and this
    # signature fits both.
    def get_name(self, *args: Any, **kwargs: Any) -> str | None:
        # None falls back to the serializer class name, the way a hand-written serializer is named.
        return None

    # None identifies the component by its serializer, the same as its name, so drf-spectacular
    # still warns when two serializer classes publish the same component name.
    def get_identity(self, auto_schema: AutoSchema, direction: Direction) -> Any:
        return None
