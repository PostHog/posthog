import json
from abc import ABC, abstractmethod
from collections.abc import Generator, Sequence
from typing import Any, Generic, Self, TypeVar

from django.db.models import Model

from pydantic import BaseModel, Field
from pydantic_avro import AvroBase

from posthog.schema import ActorsPropertyTaxonomyResponse, EventTaxonomyItem, TeamTaxonomyItem

from posthog.models import DataWarehouseTable, GroupTypeMapping, PropertyDefinition, Team

T = TypeVar("T", bound=Model)


class BaseSnapshot(AvroBase, ABC, Generic[T]):
    @classmethod
    @abstractmethod
    def serialize_for_team(cls, *, team_id: int) -> Generator[Self, None, None]:
        raise NotImplementedError

    @classmethod
    @abstractmethod
    def deserialize_for_team(cls, models: Sequence[Self], *, team_id: int, project_id: int) -> Generator[T, None, None]:
        raise NotImplementedError


# posthog/models/team.py
class TeamSnapshot(BaseSnapshot[Team]):
    name: str
    test_account_filters: str

    @classmethod
    def serialize_for_team(cls, *, team_id: int):
        team = Team.objects.get(pk=team_id)
        yield TeamSnapshot(name=team.name, test_account_filters=json.dumps(team.test_account_filters))

    @classmethod
    def deserialize_for_team(
        cls, models: Sequence[Self], *, team_id: int, project_id: int
    ) -> Generator[Team, None, None]:
        for model in models:
            yield Team(
                id=team_id,
                project_id=project_id,
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
    def serialize_for_team(cls, *, team_id: int):
        for prop in PropertyDefinition.objects.filter(team_id=team_id).iterator(500):
            yield PropertyDefinitionSnapshot(
                name=prop.name,
                is_numerical=prop.is_numerical,
                property_type=prop.property_type,
                type=prop.type,
                group_type_index=prop.group_type_index,
            )

    @classmethod
    def deserialize_for_team(cls, models: Sequence[Self], *, team_id: int, project_id: int):
        for model in models:
            yield PropertyDefinition(
                name=model.name,
                is_numerical=model.is_numerical,
                property_type=model.property_type,
                type=model.type,
                group_type_index=model.group_type_index,
                team_id=team_id,
                project_id=project_id,
            )


# posthog/models/group_type_mapping.py
class GroupTypeMappingSnapshot(BaseSnapshot[GroupTypeMapping]):
    group_type: str
    group_type_index: int
    name_singular: str | None
    name_plural: str | None

    @classmethod
    def serialize_for_team(cls, *, team_id: int):
        for mapping in GroupTypeMapping.objects.filter(team_id=team_id).iterator(500):
            yield GroupTypeMappingSnapshot(
                group_type=mapping.group_type,
                group_type_index=mapping.group_type_index,
                name_singular=mapping.name_singular,
                name_plural=mapping.name_plural,
            )

    @classmethod
    def deserialize_for_team(cls, models: Sequence[Self], *, team_id: int, project_id: int):
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
    columns: str

    @classmethod
    def serialize_for_team(cls, *, team_id: int):
        for table in DataWarehouseTable.objects.filter(team_id=team_id).iterator(500):
            yield DataWarehouseTableSnapshot(
                name=table.name,
                format=table.format,
                columns=json.dumps(table.columns) if table.columns else "",
            )

    @classmethod
    def deserialize_for_team(cls, models: Sequence[Self], *, team_id: int, project_id: int):
        for model in models:
            yield DataWarehouseTable(
                name=model.name,
                format=model.format,
                columns=json.loads(model.columns) if model.columns else {},
                url_pattern="http://localhost",  # Hardcoded. It's not important for evaluations what the value is.
                team_id=team_id,
            )


class PostgresTeamDataSnapshot(BaseModel):
    team: str
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


class ClickhouseTeamDataSnapshot(BaseModel):
    event_taxonomy: str
    properties_taxonomy: str
    actors_property_taxonomy: str


class TeamEvaluationSnapshot(BaseModel):
    team_id: int
    postgres: PostgresTeamDataSnapshot
    clickhouse: ClickhouseTeamDataSnapshot


class DatasetInput(BaseModel):
    team_id: int
    trace_id: str | None = Field(default=None)
    input: dict[str, Any] = Field(default_factory=dict)
    expected: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class EvalsDockerImageConfig(BaseModel):
    class Config:
        extra = "allow"

    aws_bucket_name: str
    """
    AWS S3 bucket name for the raw snapshots for all projects.
    """
    aws_endpoint_url: str
    """
    AWS S3 endpoint URL for the raw snapshots for all projects.
    """
    team_snapshots: list[TeamEvaluationSnapshot]
    """
    Raw snapshots for all projects.

    """
    experiment_id: str
    """
    ID of the experiment.
    """
    experiment_name: str
    """
    Name of the experiment.
    """

    dataset_id: str
    """
    ID of the dataset.
    """
    dataset_name: str
    """
    Name of the dataset.
    """
    dataset_inputs: list[DatasetInput]
    """
    Parsed dataset.
    """
