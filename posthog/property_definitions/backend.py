import enum
from collections.abc import Iterable, Sequence

from django.db import models
from django.db.models.functions import Coalesce

from posthog.models import Team
from posthog.models.property import PropertyName
from posthog.models.property_definition import PropertyDefinition as _PropertyDefinition


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
    def __get_queryset_for_team(self, team: Team):
        return _PropertyDefinition.objects.alias(
            effective_project_id=Coalesce("project_id", "team_id", output_field=models.BigIntegerField())
        ).filter(effective_project_id=team.project_id)

    def get_property_types(
        self,
        team: Team,
        object_type: PropertyObjectType,
        *,
        group_type_index: int | None,  # TODO: clean up typing
        names: Iterable[PropertyName] | None = None,
    ) -> Iterable[tuple[PropertyName, PropertyValueType]]:
        qs = self.__get_queryset_for_team(team).filter(type=object_type)
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
        team: Team,
        object_type: PropertyObjectType,
        name: PropertyName,
        *,
        group_type_index: int | None = None,
    ) -> PropertyValueType:
        qs = self.__get_queryset_for_team(team).filter(type=object_type, name=name)
        if object_type == PropertyObjectType.Group:
            assert group_type_index is not None
            qs = qs.filter(group_type_index=group_type_index)
        else:
            assert group_type_index is None
        try:
            return qs.get()
        except _PropertyDefinition.DoesNotExist:
            raise PropertyDefinitionDoesNotExist()

    def find_properties(
        self, team: Team, object_type: PropertyObjectType, name: PropertyName, limit: int
    ) -> tuple[int, Sequence[PropertyName, PropertyValueType]]:
        qs = self.__get_queryset_for_team(team).filter(type=object_type, name__contains=name)
        return qs.count(), qs.values_list("name", "property_type")[:limit]


backend = PropertyDefinitionsBackend()
