from collections.abc import Iterable, Sequence

from django.db import models
from django.db.models.functions import Coalesce

from posthog.models import Team
from posthog.models.property import PropertyName
from posthog.models.property_definition import PropertyDefinition as _PropertyDefinition, PropertyType


PropertyDefinitionType = _PropertyDefinition.Type


class PropertyDefinitionDoesNotExist(Exception):
    pass


class PropertyDefinitionsBackend:
    def __get_queryset_for_team(self, team: Team):
        return _PropertyDefinition.objects.alias(
            effective_project_id=Coalesce("project_id", "team_id", output_field=models.BigIntegerField())
        ).filter(effective_project_id=team.project_id)  # type: ignore

    def get_property_type(
        self,
        team: Team,
        type: PropertyDefinitionType,
        name: PropertyName,
        *,
        group_type_index: int | None = None,
    ) -> PropertyType:
        qs = self.__get_queryset_for_team(team).filter(type=type, name=name)
        if type == PropertyDefinitionType.GROUP:
            assert group_type_index is not None
            qs = qs.filter(group_type_index=group_type_index)
        else:
            assert group_type_index is None
        try:
            return qs.get().property_type
        except _PropertyDefinition.DoesNotExist:
            raise PropertyDefinitionDoesNotExist()

    def get_property_types(
        self,
        team: Team,
        type: PropertyDefinitionType,
        *,
        group_type_index: int | None = None,
        names: Iterable[PropertyName] | None = None,
    ) -> Iterable[tuple[PropertyName, PropertyType]]:
        qs = self.__get_queryset_for_team(team).filter(type=type)
        if type == PropertyDefinitionType.GROUP:
            assert group_type_index is not None
            qs = qs.filter(group_type_index=group_type_index)
        else:
            assert group_type_index is None
        if names is not None:
            qs = qs.filter(name__in=names)
        return qs.values_list("name", "property_type")

    def find_properties(
        self, team: Team, type: PropertyDefinitionType, name: PropertyName, limit: int
    ) -> tuple[int, Sequence[PropertyName, PropertyType]]:
        qs = self.__get_queryset_for_team(team).filter(type=type, name__contains=name)
        return qs.count(), qs.values_list("name", "property_type")[:limit]


backend = PropertyDefinitionsBackend()
