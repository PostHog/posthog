import json
from abc import ABC, abstractmethod
from collections.abc import Generator, Sequence
from typing import Generic, Self, TypeVar

from django.db.models import Model
from pydantic import BaseModel
from pydantic_avro import AvroBase

from posthog.models import DataWarehouseTable, PropertyDefinition, Team
from posthog.schema import EventTaxonomyItem, TeamTaxonomyItem


class EvalsDockerImageConfig(BaseModel):
    class Config:
        extra = "allow"

    bucket_name: str
    endpoint_url: str
    project_snapshots: list["Snapshot"]


T = TypeVar("T", bound=Model)


class BaseSchema(AvroBase, ABC, Generic[T]):
    @classmethod
    @abstractmethod
    def serialize_for_project(cls, project_id: int) -> Generator[Self, None, None]:
        raise NotImplementedError

    @classmethod
    @abstractmethod
    def deserialize_for_project(cls, project_id: int, models: Sequence[Self]) -> Generator[T, None, None]:
        raise NotImplementedError


class TeamSchema(BaseSchema[Team]):
    name: str
    test_account_filters: str

    @classmethod
    def serialize_for_project(cls, project_id: int):
        team = Team.objects.get(pk=project_id)
        yield TeamSchema(name=team.name, test_account_filters=json.dumps(team.test_account_filters))

    @classmethod
    def deserialize_for_project(cls, project_id: int, models: Sequence[Self]) -> Generator[Team, None, None]:
        for model in models:
            yield Team(id=project_id, name=model.name, test_account_filters=json.loads(model.test_account_filters))


# posthog/models/property_definition.py
class PropertyDefinitionSchema(BaseSchema[PropertyDefinition]):
    name: str
    is_numerical: bool
    property_type: str | None
    type: int
    group_type_index: int | None

    @classmethod
    def serialize_for_project(cls, project_id: int):
        for prop in PropertyDefinition.objects.filter(project_id=project_id).iterator(500):
            yield PropertyDefinitionSchema(
                name=prop.name,
                is_numerical=prop.is_numerical,
                property_type=prop.property_type,
                type=prop.type,
                group_type_index=prop.group_type_index,
            )

    @classmethod
    def deserialize_for_project(cls, project_id: int, models: Sequence[Self]):
        for model in models:
            yield PropertyDefinition(
                name=model.name,
                is_numerical=model.is_numerical,
                property_type=model.property_type,
                type=model.type,
                group_type_index=model.group_type_index,
                team_id=project_id,
            )


# posthog/models/warehouse/table.py
class DataWarehouseTableSchema(BaseSchema[DataWarehouseTable]):
    name: str
    format: str
    columns: list[str]

    @classmethod
    def serialize_for_project(cls, project_id: int):
        for table in DataWarehouseTable.objects.filter(team_id=project_id).iterator(500):
            yield DataWarehouseTableSchema(
                name=table.name,
                format=table.format,
                columns=table.columns,
            )

    @classmethod
    def deserialize_for_project(cls, project_id: int, models: Sequence[Self]):
        for model in models:
            yield DataWarehouseTable(
                name=model.name,
                format=model.format,
                columns=model.columns,
                url_pattern="http://localhost",
                team_id=project_id,
            )


class PostgresProjectDataSnapshot(BaseModel):
    project: str
    property_definitions: str
    data_warehouse_tables: str


# posthog/hogql_queries/ai/team_taxonomy_query_runner.py
class TeamTaxonomyItemSchema(AvroBase):
    results: list[TeamTaxonomyItem]


# posthog/hogql_queries/ai/event_taxonomy_query_runner.py
class PropertyTaxonomySchema(AvroBase):
    event: str
    results: list[EventTaxonomyItem]


class ClickhouseProjectDataSnapshot(BaseModel):
    event_taxonomy: str
    properties_taxonomy: str


class ProjectSnapshot(BaseModel):
    team_snapshot: TeamTaxonomyItemSchema
    postgres_snapshot: PostgresProjectDataSnapshot
    clickhouse_snapshot: ClickhouseProjectDataSnapshot


class Snapshot(BaseModel):
    project: int
    postgres: PostgresProjectDataSnapshot
    clickhouse: ClickhouseProjectDataSnapshot
