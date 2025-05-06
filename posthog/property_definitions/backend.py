import enum
from collections.abc import Iterable, Sequence

import posthog.models.property_definition as models


PropertyName = str


class PropertyObjectType(enum.Enum):  # TODO: unify with model definition
    Event = 1
    Person = 2
    Group = 3
    Session = 4


class PropertyValueType(enum.StrEnum):  # TODO: unify with model definition, taxonomy.py
    Datetime = "DateTime"
    String = "String"
    Numeric = "Numeric"
    Boolean = "Boolean"
    Duration = "Duration"


class PropertyDefinitionDoesNotExist(Exception):
    pass


class PropertyDefinitionsBackend:
    def get_property_types(
        self,
        team_id: int,
        object_type: PropertyObjectType,
        *,
        group_type_index: int | None,  # TODO: clean up typing
        names: Iterable[PropertyName] | None = None,
    ) -> Iterable[tuple[PropertyName, PropertyValueType]]:
        qs = models.PropertyDefinition.objects.filter(team_id=team_id, type=object_type)
        if object_type == PropertyObjectType.Group:
            assert group_type_index is not None
            qs = qs.filter(group_type_index=group_type_index)
        else:
            assert group_type_index is None
        if names is not None:
            qs = qs.filter(name__in=names)
        return qs.values_list("name", "property_type")

    def get_property_type(
        self,
        team_id: int,
        object_type: PropertyObjectType,
        name: PropertyName,
        *,
        group_type_index: int | None = None,
    ) -> PropertyValueType:
        qs = models.PropertyDefinition.objects.filter(team_id=team_id, type=object_type, name=name)
        if object_type == PropertyObjectType.Group:
            assert group_type_index is not None
            qs = qs.filter(group_type_index=group_type_index)
        else:
            assert group_type_index is None
        try:
            return qs.get()
        except models.PropertyDefinition.DoesNotExist:
            raise PropertyDefinitionDoesNotExist()

    def find_properties(
        self, team_id: int, object_type: PropertyObjectType, name: PropertyName, limit: int
    ) -> tuple[int, Sequence[PropertyName, PropertyValueType]]:
        qs = models.PropertyDefinition.objects.filter(team_id=team_id, type=object_type, name__contains=name)
        return qs.count(), qs.values_list("name", "property_type")[:limit]


backend = PropertyDefinitionsBackend()
