from contextlib import contextmanager
from tempfile import TemporaryFile

import botocore.exceptions
import dagster
from dagster_aws.s3 import S3Resource
from django.conf import settings
from fastavro import parse_schema, writer
from pydantic import BaseModel
from pydantic_avro import AvroBase

from dags.common import JobOwners
from posthog.hogql_queries.ai.event_taxonomy_query_runner import EventTaxonomyQueryRunner
from posthog.hogql_queries.ai.team_taxonomy_query_runner import TeamTaxonomyQueryRunner
from posthog.models import DataWarehouseTable, PropertyDefinition, Team
from posthog.schema import EventTaxonomyItem, EventTaxonomyQuery, TeamTaxonomyItem, TeamTaxonomyQuery


# posthog/models/property_definition.py
class PropertyDefinitionSchema(AvroBase):
    name: str
    is_numerical: bool
    property_type: str | None
    type: int
    group_type_index: int | None


def compose_dump_path(project_id: int, file_name: str) -> str:
    return f"{settings.OBJECT_STORAGE_MAX_AI_EVALS_FOLDER}/models/{project_id}/{file_name}"


def check_dump_exists(s3: S3Resource, file_key: str) -> bool:
    """Check if a file exists in S3"""
    try:
        s3.get_client().head_object(Bucket=settings.OBJECT_STORAGE_BUCKET, Key=file_key)
        return True
    except botocore.exceptions.ClientError as e:
        if e.response["Error"]["Code"] == "404":
            return False
        raise


@contextmanager
def dump_model(*, s3: S3Resource, schema: type[AvroBase], file_key: str):
    with TemporaryFile() as f:

        def dump(models: list[AvroBase]):
            writer(f, parse_schema(schema.avro_schema()), [model.model_dump() for model in models])
            s3.get_client().upload_fileobj(f, settings.OBJECT_STORAGE_BUCKET, file_key)

        yield dump


SnapshotModelOutput = tuple[str, str]


def snapshot_property_definitions(s3: S3Resource, project_id: int) -> SnapshotModelOutput:
    file_key = compose_dump_path(project_id, "prop_defs.avro")

    with dump_model(s3=s3, schema=PropertyDefinitionSchema, file_key=file_key) as dump:
        models_to_dump: list[PropertyDefinitionSchema] = []
        for prop in PropertyDefinition.objects.filter(project_id=project_id).iterator(500):
            model = PropertyDefinitionSchema(
                name=prop.name,
                is_numerical=prop.is_numerical,
                property_type=prop.property_type,
                type=prop.type,
                group_type_index=prop.group_type_index,
            )
            models_to_dump.append(model)
        dump(models_to_dump)
    return "property_definitions", file_key


# posthog/models/warehouse/table.py
class DataWarehouseTableSchema(AvroBase):
    name: str
    format: str
    columns: list[str]


def snapshot_data_warehouse_tables(s3: S3Resource, project_id: int):
    file_key = compose_dump_path(project_id, "dwh_tables.avro")

    with dump_model(s3=s3, schema=DataWarehouseTableSchema, file_key=file_key) as dump:
        models_to_dump: list[DataWarehouseTableSchema] = []
        for table in DataWarehouseTable.objects.filter(team_id=project_id).iterator(500):
            model = DataWarehouseTableSchema(
                name=table.name,
                format=table.format,
                columns=table.columns,
            )
            models_to_dump.append(model)
        dump(models_to_dump)
    return "data_warehouse_tables", file_key


class PostgresProjectDataSnapshot(BaseModel):
    property_definitions: str
    data_warehouse_tables: str


@dagster.op(
    description="Snapshots Postgres project data (property definitions, DWH schema, etc.)",
    tags={"owner": JobOwners.TEAM_MAX_AI.value},
)
def snapshot_postgres_project_data(
    context: dagster.OpExecutionContext, project_id: int, s3: S3Resource
) -> PostgresProjectDataSnapshot:
    deps = dict(
        (
            snapshot_property_definitions(s3, project_id),
            snapshot_data_warehouse_tables(s3, project_id),
        )
    )
    context.log_event(
        dagster.AssetMaterialization(
            asset_key="project_postgres_snapshots",
            description="Avro snapshots of project Postgres data",
            metadata={"project_id": project_id, **deps},
            tags={"owner": JobOwners.TEAM_MAX_AI.value},
        )
    )
    return PostgresProjectDataSnapshot.model_validate(deps)


class TeamTaxonomyItemSchema(AvroBase):
    results: list[TeamTaxonomyItem]


def snapshot_events_taxonomy(s3: S3Resource, team: Team):
    file_key = compose_dump_path(team.id, "events_taxonomy.avro")
    res = TeamTaxonomyQueryRunner(query=TeamTaxonomyQuery(), team=team).calculate()
    if not res.results:
        raise ValueError("No results from events taxonomy query")
    with dump_model(s3=s3, schema=TeamTaxonomyItemSchema, file_key=file_key) as dump:
        dumped_items = TeamTaxonomyItemSchema(results=res.results)
        dump([dumped_items])
    return file_key, res.results


class PropertyTaxonomySchema(AvroBase):
    event: str
    results: list[EventTaxonomyItem]


def snapshot_properties_taxonomy(
    context: dagster.OpExecutionContext, s3: S3Resource, team: Team, events: list[TeamTaxonomyItemSchema]
):
    results: list[PropertyTaxonomySchema] = []
    for item in events:
        context.log.info(f"Snapshotting properties taxonomy for event {item.event}")
        res = EventTaxonomyQueryRunner(
            query=EventTaxonomyQuery(event=item.event),
            team=team,
        ).calculate()
        results.append(PropertyTaxonomySchema(event=item.event, results=res.results))
    file_key = compose_dump_path(team.id, "properties_taxonomy.avro")
    context.log.info(f"Dumping properties taxonomy to {file_key}")
    with dump_model(s3=s3, schema=PropertyTaxonomySchema, file_key=file_key) as dump:
        dump(results)
    return file_key


class ClickhouseProjectDataSnapshot(BaseModel):
    event_taxonomy: str
    properties_taxonomy: str


@dagster.op(
    description="Snapshots ClickHouse project data",
    tags={"owner": JobOwners.TEAM_MAX_AI.value},
)
def snapshot_clickhouse_project_data(
    context: dagster.OpExecutionContext, project_id: int, s3: S3Resource
) -> ClickhouseProjectDataSnapshot:
    team = Team.objects.get(id=project_id)
    event_taxonomy_file_key, event_taxonomy = snapshot_events_taxonomy(s3, team)
    properties_taxonomy_file_key = snapshot_properties_taxonomy(context, s3, team, event_taxonomy)
    context.log_event(
        dagster.AssetMaterialization(
            asset_key="project_clickhouse_snapshots",
            description="Avro snapshots of project ClickHouse data",
            metadata={
                "project_id": project_id,
                "event_taxonomy": event_taxonomy_file_key,
                "properties_taxonomy": properties_taxonomy_file_key,
            },
            tags={"owner": JobOwners.TEAM_MAX_AI.value},
        )
    )
    return ClickhouseProjectDataSnapshot(
        event_taxonomy=event_taxonomy_file_key,
        properties_taxonomy=properties_taxonomy_file_key,
    )
