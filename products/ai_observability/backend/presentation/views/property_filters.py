from collections.abc import Sequence

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from pydantic import TypeAdapter, ValidationError
from rest_framework import serializers

from posthog.schema import AnyPropertyFilterDiscriminated

from ...facade import api

QUERY_SCOPE = "query:read"
QUERY_SCOPE_REQUIRED = (
    f"Filters of type hogql, data_warehouse and data_warehouse_person_property need the {QUERY_SCOPE} scope. "
    "Use a key that has it, or remove those filters."
)

_PROPERTY_FILTERS = TypeAdapter(list[AnyPropertyFilterDiscriminated])


@extend_schema_field(OpenApiTypes.STR)
class PropertyFiltersField(serializers.Field):
    def to_internal_value(self, data: object) -> tuple[AnyPropertyFilterDiscriminated, ...]:
        try:
            return tuple(_PROPERTY_FILTERS.validate_json(serializers.CharField().run_validation(data)))
        except ValidationError as error:
            raise serializers.ValidationError("Expected a JSON list of property filters.") from error


def filters_need_query_scope(filters: Sequence[AnyPropertyFilterDiscriminated]) -> bool:
    return any(isinstance(prop, api.QUERY_SCOPED_FILTERS) for prop in filters)
