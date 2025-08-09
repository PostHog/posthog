from collections.abc import Sequence
from contextlib import contextmanager
from tempfile import TemporaryFile

import botocore.exceptions
import dagster
from dagster_aws.s3 import S3Resource
from django.conf import settings
from fastavro import parse_schema, writer
from pydantic_avro import AvroBase

from dags.common import JobOwners
from dags.max_ai.utils import compose_clickhouse_dump_path, compose_postgres_dump_path
from ee.hogai.eval.schema import (
    ActorsPropertyTaxonomySchema,
    ClickhouseProjectDataSnapshot,
    DataWarehouseTableSchema,
    GroupTypeMappingSchema,
    PostgresProjectDataSnapshot,
    PropertyDefinitionSchema,
    PropertyTaxonomySchema,
    TeamSchema,
    TeamTaxonomyItemSchema,
)
from posthog.hogql_queries.ai.actors_property_taxonomy_query_runner import ActorsPropertyTaxonomyQueryRunner
from posthog.hogql_queries.ai.event_taxonomy_query_runner import EventTaxonomyQueryRunner
from posthog.hogql_queries.ai.team_taxonomy_query_runner import TeamTaxonomyQueryRunner
from posthog.models import GroupTypeMapping, Team
from posthog.schema import ActorsPropertyTaxonomyQuery, EventTaxonomyQuery, TeamTaxonomyItem, TeamTaxonomyQuery


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
        parsed_schema = parse_schema(schema.avro_schema())

        def dump(models: Sequence[AvroBase]):
            writer(f, parsed_schema, (model.model_dump() for model in models))

        yield dump

        f.seek(0)
        s3.get_client().upload_fileobj(f, settings.OBJECT_STORAGE_BUCKET, file_key)


SnapshotModelOutput = tuple[str, str]


def snapshot_project(s3: S3Resource, project_id: int) -> SnapshotModelOutput:
    file_key = compose_postgres_dump_path(project_id, "team.avro")
    with dump_model(s3=s3, schema=TeamSchema, file_key=file_key) as dump:
        dump(TeamSchema.serialize_for_project(project_id))
    return "project", file_key


def snapshot_property_definitions(s3: S3Resource, project_id: int) -> SnapshotModelOutput:
    file_key = compose_postgres_dump_path(project_id, "prop_defs.avro")
    with dump_model(s3=s3, schema=PropertyDefinitionSchema, file_key=file_key) as dump:
        dump(PropertyDefinitionSchema.serialize_for_project(project_id))
    return "property_definitions", file_key


def snapshot_group_type_mappings(s3: S3Resource, project_id: int) -> SnapshotModelOutput:
    file_key = compose_postgres_dump_path(project_id, "group_type_mappings.avro")
    with dump_model(s3=s3, schema=GroupTypeMappingSchema, file_key=file_key) as dump:
        dump(GroupTypeMappingSchema.serialize_for_project(project_id))
    return "group_type_mappings", file_key


def snapshot_data_warehouse_tables(s3: S3Resource, project_id: int):
    file_key = compose_postgres_dump_path(project_id, "dwh_tables.avro")
    with dump_model(s3=s3, schema=DataWarehouseTableSchema, file_key=file_key) as dump:
        dump(DataWarehouseTableSchema.serialize_for_project(project_id))
    return "data_warehouse_tables", file_key


@dagster.op(
    description="Snapshots Postgres project data (property definitions, DWH schema, etc.)",
    tags={"owner": JobOwners.TEAM_MAX_AI.value},
)
def snapshot_postgres_project_data(
    context: dagster.OpExecutionContext, project_id: int, s3: S3Resource
) -> PostgresProjectDataSnapshot:
    deps = dict(
        (
            snapshot_project(s3, project_id),
            snapshot_property_definitions(s3, project_id),
            snapshot_group_type_mappings(s3, project_id),
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
    return PostgresProjectDataSnapshot(**deps)


def snapshot_events_taxonomy(s3: S3Resource, team: Team):
    file_key = compose_clickhouse_dump_path(team.id, "events_taxonomy.avro")
    res = TeamTaxonomyQueryRunner(query=TeamTaxonomyQuery(), team=team).calculate()
    if not res.results:
        raise ValueError("No results from events taxonomy query")
    with dump_model(s3=s3, schema=TeamTaxonomyItemSchema, file_key=file_key) as dump:
        dumped_items = TeamTaxonomyItemSchema(results=res.results)
        dump([dumped_items])
    return file_key, res.results


def snapshot_properties_taxonomy(
    context: dagster.OpExecutionContext, s3: S3Resource, team: Team, events: list[TeamTaxonomyItem]
):
    results: list[PropertyTaxonomySchema] = []
    for item in events:
        context.log.info(f"Snapshotting properties taxonomy for event {item.event}")
        res = EventTaxonomyQueryRunner(
            query=EventTaxonomyQuery(event=item.event),
            team=team,
        ).calculate()
        results.append(PropertyTaxonomySchema(event=item.event, results=res.results))
    file_key = compose_clickhouse_dump_path(team.id, "properties_taxonomy.avro")
    context.log.info(f"Dumping properties taxonomy to {file_key}")
    with dump_model(s3=s3, schema=PropertyTaxonomySchema, file_key=file_key) as dump:
        dump(results)
    return file_key


def snapshot_actors_property_taxonomy(context: dagster.OpExecutionContext, s3: S3Resource, team: Team):
    # Snapshot all group type mappings and person
    results: list[PropertyTaxonomySchema] = []
    group_type_mappings: list[int | None] = [
        None,
        *(g.group_type_index for g in GroupTypeMapping.objects.filter(team=team)),
    ]
    for index in group_type_mappings:
        log_entity = f"group type {index}" if index else "persons"
        context.log.info(f"Snapshotting properties taxonomy for {log_entity}")
        res = ActorsPropertyTaxonomyQueryRunner(
            query=ActorsPropertyTaxonomyQuery(group_type_index=index, maxPropertyValues=25),
            team=team,
        ).calculate()
        results.append(ActorsPropertyTaxonomySchema(group_type_index=index, results=res.results))
    file_key = compose_clickhouse_dump_path(team.id, "actors_property_taxonomy.avro")
    context.log.info(f"Dumping actors property taxonomy to {file_key}")
    with dump_model(s3=s3, schema=ActorsPropertyTaxonomySchema, file_key=file_key) as dump:
        dump(results)
    return file_key


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
    actors_property_taxonomy_file_key = snapshot_actors_property_taxonomy(context, s3, team)
    materialized_result = ClickhouseProjectDataSnapshot(
        event_taxonomy=event_taxonomy_file_key,
        properties_taxonomy=properties_taxonomy_file_key,
        actors_property_taxonomy=actors_property_taxonomy_file_key,
    )
    context.log_event(
        dagster.AssetMaterialization(
            asset_key="project_clickhouse_snapshots",
            description="Avro snapshots of project ClickHouse data",
            metadata={
                "project_id": project_id,
                **materialized_result.model_dump(),
            },
            tags={"owner": JobOwners.TEAM_MAX_AI.value},
        )
    )
    return materialized_result
