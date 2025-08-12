from collections.abc import Callable, Iterable, Iterator, Sequence
from contextlib import contextmanager
from itertools import islice
from tempfile import TemporaryFile
from typing import TypeVar

import botocore.exceptions
import dagster
from dagster_aws.s3 import S3Resource
from django.conf import settings
from fastavro import parse_schema, writer
from pydantic_avro import AvroBase
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

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
from posthog.errors import InternalCHQueryError
from posthog.hogql_queries.ai.actors_property_taxonomy_query_runner import (
    ActorsPropertyTaxonomyQueryRunner,
)
from posthog.hogql_queries.ai.event_taxonomy_query_runner import (
    EventTaxonomyQueryRunner,
)
from posthog.hogql_queries.ai.team_taxonomy_query_runner import TeamTaxonomyQueryRunner
from posthog.models import GroupTypeMapping, Team
from posthog.models.property_definition import PropertyDefinition
from posthog.schema import (
    ActorsPropertyTaxonomyQuery,
    EventTaxonomyQuery,
    TeamTaxonomyItem,
    TeamTaxonomyQuery,
)


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


def snapshot_project(s3: S3Resource, project_id: int, code_version: str | None = None) -> SnapshotModelOutput:
    file_key = compose_postgres_dump_path(project_id, "team", code_version)
    with dump_model(s3=s3, schema=TeamSchema, file_key=file_key) as dump:
        dump(TeamSchema.serialize_for_project(project_id))
    return "project", file_key


def snapshot_property_definitions(
    s3: S3Resource, project_id: int, code_version: str | None = None
) -> SnapshotModelOutput:
    file_key = compose_postgres_dump_path(project_id, "prop_defs", code_version)
    with dump_model(s3=s3, schema=PropertyDefinitionSchema, file_key=file_key) as dump:
        dump(PropertyDefinitionSchema.serialize_for_project(project_id))
    return "property_definitions", file_key


def snapshot_group_type_mappings(
    s3: S3Resource, project_id: int, code_version: str | None = None
) -> SnapshotModelOutput:
    file_key = compose_postgres_dump_path(project_id, "group_type_mappings", code_version)
    with dump_model(s3=s3, schema=GroupTypeMappingSchema, file_key=file_key) as dump:
        dump(GroupTypeMappingSchema.serialize_for_project(project_id))
    return "group_type_mappings", file_key


def snapshot_data_warehouse_tables(s3: S3Resource, project_id: int, code_version: str | None = None):
    file_key = compose_postgres_dump_path(project_id, "dwh_tables", code_version)
    with dump_model(s3=s3, schema=DataWarehouseTableSchema, file_key=file_key) as dump:
        dump(DataWarehouseTableSchema.serialize_for_project(project_id))
    return "data_warehouse_tables", file_key


@dagster.op(
    description="Snapshots Postgres project data (property definitions, DWH schema, etc.)",
    tags={"owner": JobOwners.TEAM_MAX_AI.value},
    code_version="v1",
)
def snapshot_postgres_project_data(
    context: dagster.OpExecutionContext, project_id: int, s3: S3Resource
) -> PostgresProjectDataSnapshot:
    context.log.info(f"Snapshotting Postgres project data for {project_id}")
    deps = dict(
        (
            snapshot_project(s3, project_id, context.op_def.version),
            snapshot_property_definitions(s3, project_id, context.op_def.version),
            snapshot_group_type_mappings(s3, project_id, context.op_def.version),
            snapshot_data_warehouse_tables(s3, project_id, context.op_def.version),
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


C = TypeVar("C")


@retry(retry=retry_if_exception_type(InternalCHQueryError), stop=stop_after_attempt(4), wait=wait_exponential(min=8))
def call_query_runner(callable: Callable[[], C]) -> C:
    return callable()


def snapshot_properties_taxonomy(
    context: dagster.OpExecutionContext, s3: S3Resource, file_key: str, team: Team, events: list[TeamTaxonomyItem]
):
    results: list[PropertyTaxonomySchema] = []

    def snapshot_event(item: TeamTaxonomyItem):
        return call_query_runner(
            lambda: EventTaxonomyQueryRunner(
                query=EventTaxonomyQuery(event=item.event),
                team=team,
            ).calculate()
        )

    for item in events:
        context.log.info(f"Snapshotting properties taxonomy for event {item.event} of {team.id}")
        results.append(PropertyTaxonomySchema(event=item.event, results=snapshot_event(item).results))

    context.log.info(f"Dumping properties taxonomy to {file_key}")
    with dump_model(s3=s3, schema=PropertyTaxonomySchema, file_key=file_key) as dump:
        dump(results)


def snapshot_events_taxonomy(
    context: dagster.OpExecutionContext, s3: S3Resource, team: Team, code_version: str | None = None
):
    # Check if files are cached
    events_file_key = compose_clickhouse_dump_path(team.id, "events_taxonomy", code_version=code_version)
    properties_file_key = compose_clickhouse_dump_path(team.id, "properties_taxonomy", code_version=code_version)
    if check_dump_exists(s3, events_file_key) and check_dump_exists(s3, properties_file_key):
        context.log.info(f"Skipping events and properties taxonomy snapshot for {team.id} because it already exists")
        return events_file_key, properties_file_key

    context.log.info(f"Snapshotting events taxonomy for {team.id}")

    res = call_query_runner(lambda: TeamTaxonomyQueryRunner(query=TeamTaxonomyQuery(), team=team).calculate())
    if not res.results:
        raise ValueError("No results from events taxonomy query")

    # Dump properties
    snapshot_properties_taxonomy(context, s3, properties_file_key, team, res.results)

    # Dump later to ensure caching
    with dump_model(s3=s3, schema=TeamTaxonomyItemSchema, file_key=events_file_key) as dump:
        dumped_items = TeamTaxonomyItemSchema(results=res.results)
        dump([dumped_items])

    return events_file_key, properties_file_key


T = TypeVar("T")


def chunked(iterable: Iterable[T], size: int = 200) -> Iterator[list[T]]:
    it = iter(iterable)
    while True:
        batch = list(islice(it, size))
        if not batch:
            break
        yield batch


def snapshot_actors_property_taxonomy(
    context: dagster.OpExecutionContext, s3: S3Resource, team: Team, code_version: str | None = None
):
    file_key = compose_clickhouse_dump_path(team.id, "actors_property_taxonomy", code_version=code_version)
    if check_dump_exists(s3, file_key):
        context.log.info(f"Skipping actors property taxonomy snapshot for {team.id} because it already exists")
        return file_key

    # Snapshot all group type mappings and person
    results: list[ActorsPropertyTaxonomySchema] = []
    group_type_mappings: list[int | None] = [
        None,
        *(g.group_type_index for g in GroupTypeMapping.objects.filter(team=team)),
    ]

    for index in group_type_mappings:
        is_group = index is not None
        log_entity = f"group type {index}" if is_group else "persons"
        context.log.info(f"Snapshotting properties taxonomy for {log_entity}")

        # Retrieve saved property definitions for the group type or person
        property_defs = (
            PropertyDefinition.objects.filter(
                team=team,
                type=PropertyDefinition.Type.GROUP if is_group else PropertyDefinition.Type.PERSON,
                group_type_index=index,
            )
            .values_list("name", flat=True)
            .iterator(chunk_size=200)
        )

        # Query ClickHouse in batches of 200 properties
        for batch in chunked(property_defs, 200):

            def snapshot(index: int | None, batch: list[str]):
                return call_query_runner(
                    lambda: ActorsPropertyTaxonomyQueryRunner(
                        query=ActorsPropertyTaxonomyQuery(groupTypeIndex=index, properties=batch, maxPropertyValues=25),
                        team=team,
                    ).calculate()
                )

            res = snapshot(index, batch)

            if not res.results:
                raise ValueError(
                    f"No results from actors property taxonomy query for group type {index} and properties {batch}"
                )

            # Snapshot queries in the same way as the toolkit expects
            for prop, prop_results in zip(batch, res.results):
                results.append(
                    ActorsPropertyTaxonomySchema(property=prop, group_type_index=index, results=prop_results)
                )

    context.log.info(f"Dumping actors property taxonomy to {file_key}")
    with dump_model(s3=s3, schema=ActorsPropertyTaxonomySchema, file_key=file_key) as dump:
        dump(results)
    return file_key


@dagster.op(
    description="Snapshots ClickHouse project data",
    tags={"owner": JobOwners.TEAM_MAX_AI.value},
    code_version="v1",
)
def snapshot_clickhouse_project_data(
    context: dagster.OpExecutionContext, project_id: int, s3: S3Resource
) -> ClickhouseProjectDataSnapshot:
    team = Team.objects.get(id=project_id)

    event_taxonomy_file_key, properties_taxonomy_file_key = snapshot_events_taxonomy(
        context, s3, team, context.op_def.version
    )
    actors_property_taxonomy_file_key = snapshot_actors_property_taxonomy(context, s3, team, context.op_def.version)

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


# TODO: timeout, retries and max parallelization, wait for ch and psql3
