from typing import TypeVar

from django.db.models import Choices

from rest_framework_dataclasses.field_utils import TypeInfo
from rest_framework_dataclasses.serializers import DataclassSerializer, SerializerFieldDefinition
from rest_framework_dataclasses.types import Dataclass

from posthog.enums import LabeledEnumType

T = TypeVar("T", bound=Dataclass)


# Enum fields carry the class labels, so posthog/openapi/enum_names.py names the OpenAPI enum after
# the class. The library pairs each value with the member name ("OPEN"), and no class carries that
# choice set. This is a comment and not a docstring because drf-spectacular copies a class docstring
# into the component description of every subclass.
class LabeledChoicesDataclassSerializer(DataclassSerializer[T]):
    def build_enum_field(self, field_name: str, type_info: TypeInfo) -> SerializerFieldDefinition:
        field_class, field_kwargs = super().build_enum_field(field_name, type_info)
        enum_class = type_info.base_type
        if isinstance(enum_class, LabeledEnumType):
            field_kwargs["choices"] = enum_class.choices
        elif issubclass(enum_class, Choices):
            field_kwargs["choices"] = enum_class.choices
        return field_class, field_kwargs
