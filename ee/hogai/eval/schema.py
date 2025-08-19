import json
from abc import ABC, abstractmethod
from collections.abc import Generator, Sequence
from typing import Generic, Self, TypeVar

from django.db.models import Model
from pydantic import BaseModel
from pydantic_avro import AvroBase

from posthog.models import (
    DataWarehouseTable,
    GroupTypeMapping,
    PropertyDefinition,
    Team,
)
from posthog.schema import (
    ActorsPropertyTaxonomyResponse,
    EventTaxonomyItem,
    TeamTaxonomyItem,
)

T = TypeVar("T", bound=Model)


class BaseSnapshot(AvroBase, ABC, Generic[T]):
    @classmethod
    @abstractmethod
    def serialize_for_project(cls, project_id: int) -> Generator[Self, None, None]:
        raise NotImplementedError

    @classmethod
    @abstractmethod
    def deserialize_for_project(
        cls, project_id: int, models: Sequence[Self], *, team_id: int
    ) -> Generator[T, None, None]:
        raise NotImplementedError


# posthog/models/team.py
class TeamSnapshot(BaseSnapshot[Team]):
    name: str
    test_account_filters: str

    @classmethod
    def serialize_for_project(cls, project_id: int):
        team = Team.objects.get(pk=project_id)
        yield TeamSnapshot(name=team.name, test_account_filters=json.dumps(team.test_account_filters))

    @classmethod
    def deserialize_for_project(cls, project_id: int, models: Sequence[Self], **kwargs) -> Generator[Team, None, None]:
        for model in models:
            yield Team(
                id=project_id,
                name=model.name,
                test_account_filters=json.loads(model.test_account_filters),
            )


# posthog/models/property_definition.py
class PropertyDefinitionSnapshot(BaseSnapshot[PropertyDefinition]):
    name: str
    is_numerical: bool
    property_type: str | None
    type: int
    group_type_index: int | None

    @classmethod
    def serialize_for_project(cls, project_id: int):
        for prop in PropertyDefinition.objects.filter(project_id=project_id).iterator(500):
            yield PropertyDefinitionSnapshot(
                name=prop.name,
                is_numerical=prop.is_numerical,
                property_type=prop.property_type,
                type=prop.type,
                group_type_index=prop.group_type_index,
            )

    @classmethod
    def deserialize_for_project(cls, project_id: int, models: Sequence[Self], **kwargs):
        for model in models:
            yield PropertyDefinition(
                name=model.name,
                is_numerical=model.is_numerical,
                property_type=model.property_type,
                type=model.type,
                group_type_index=model.group_type_index,
                team_id=project_id,
            )


# posthog/models/group_type_mapping.py
class GroupTypeMappingSnapshot(BaseSnapshot[GroupTypeMapping]):
    group_type: str
    group_type_index: int
    name_singular: str | None
    name_plural: str | None

    @classmethod
    def serialize_for_project(cls, project_id: int):
        for mapping in GroupTypeMapping.objects.filter(project_id=project_id).iterator(500):
            yield GroupTypeMappingSnapshot(
                group_type=mapping.group_type,
                group_type_index=mapping.group_type_index,
                name_singular=mapping.name_singular,
                name_plural=mapping.name_plural,
            )

    @classmethod
    def deserialize_for_project(cls, project_id: int, models: Sequence[Self], *, team_id: int):
        for model in models:
            yield GroupTypeMapping(
                group_type=model.group_type,
                group_type_index=model.group_type_index,
                name_singular=model.name_singular,
                name_plural=model.name_plural,
                team_id=team_id,
                project_id=project_id,
            )


# posthog/models/warehouse/table.py
class DataWarehouseTableSnapshot(BaseSnapshot[DataWarehouseTable]):
    name: str
    format: str
    columns: dict

    @classmethod
    def serialize_for_project(cls, project_id: int):
        for table in DataWarehouseTable.objects.filter(team_id=project_id).iterator(500):
            yield DataWarehouseTableSnapshot(
                name=table.name,
                format=table.format,
                columns=table.columns,
            )

    @classmethod
    def deserialize_for_project(cls, project_id: int, models: Sequence[Self], **kwargs):
        for model in models:
            yield DataWarehouseTable(
                name=model.name,
                format=model.format,
                columns=model.columns,
                url_pattern="http://localhost",  # Hardcoded. It's not important for evaluations what the value is.
                team_id=project_id,
            )


class PostgresProjectDataSnapshot(BaseModel):
    project: str
    property_definitions: str
    group_type_mappings: str
    data_warehouse_tables: str


# posthog/hogql_queries/ai/team_taxonomy_query_runner.py
class TeamTaxonomyItemSnapshot(AvroBase):
    results: list[TeamTaxonomyItem]


# posthog/hogql_queries/ai/event_taxonomy_query_runner.py
class PropertyTaxonomySnapshot(AvroBase):
    event: str
    results: list[EventTaxonomyItem]


# posthog/hogql_queries/ai/actors_property_taxonomy_query_runner.py
class ActorsPropertyTaxonomySnapshot(AvroBase):
    group_type_index: int | None
    property: str
    results: ActorsPropertyTaxonomyResponse


class ClickhouseProjectDataSnapshot(BaseModel):
    event_taxonomy: str
    properties_taxonomy: str
    actors_property_taxonomy: str
