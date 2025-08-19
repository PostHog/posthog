from collections.abc import Callable, Iterable, Iterator
from itertools import islice
from typing import TypeVar, cast

import dagster
from dagster_aws.s3.resources import S3Resource
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from dags.common import JobOwners
from dags.max_ai.utils import (
    check_dump_exists,
    compose_clickhouse_dump_path,
    compose_postgres_dump_path,
    dump_model,
)
from ee.hogai.eval.schema import (
    ActorsPropertyTaxonomySnapshot,
    BaseSnapshot,
    ClickhouseProjectDataSnapshot,
    DataWarehouseTableSnapshot,
    GroupTypeMappingSnapshot,
    PostgresProjectDataSnapshot,
    PropertyDefinitionSnapshot,
    PropertyTaxonomySnapshot,
    TeamSnapshot,
    TeamTaxonomyItemSnapshot,
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
    ActorsPropertyTaxonomyResponse,
    EventTaxonomyQuery,
    TeamTaxonomyItem,
    TeamTaxonomyQuery,
)

DEFAULT_RETRY_POLICY = dagster.RetryPolicy(
    max_retries=4,
    delay=2,  # 2 seconds
    backoff=dagster.Backoff.EXPONENTIAL,
    jitter=dagster.Jitter.PLUS_MINUS,
)


SchemaBound = TypeVar("SchemaBound", bound=BaseSnapshot)


def snapshot_postgres_model(
    context: dagster.OpExecutionContext,
    model_type: type[SchemaBound],
    file_name: str,
    s3: S3Resource,
    project_id: int,
    code_version: str | None = None,
) -> str:
    file_key = compose_postgres_dump_path(project_id, file_name, code_version)
    if check_dump_exists(s3, file_key):
        context.log.info(f"Skipping {file_key} because it already exists")
        return file_key
    context.log.info(f"Dumping {file_key}")
    with dump_model(s3=s3, schema=model_type, file_key=file_key) as dump:
        dump(model_type.serialize_for_project(project_id))
    return file_key


@dagster.op(
    description="Snapshots Postgres project data (property definitions, DWH schema, etc.)",
    retry_policy=DEFAULT_RETRY_POLICY,
    code_version="v1",
    tags={
        "owner": JobOwners.TEAM_MAX_AI.value,
        "dagster/max_runtime": 60 * 15,  # 15 minutes
    },
)
def snapshot_postgres_project_data(
    context: dagster.OpExecutionContext, project_id: int, s3: S3Resource
) -> PostgresProjectDataSnapshot:
    context.log.info(f"Snapshotting Postgres project data for {project_id}")
    snapshot_map: dict[str, type[BaseSnapshot]] = {
        "project": TeamSnapshot,
        "property_definitions": PropertyDefinitionSnapshot,
        "group_type_mappings": GroupTypeMappingSnapshot,
        "data_warehouse_tables": DataWarehouseTableSnapshot,
    }
    deps = {
        file_name: snapshot_postgres_model(context, model_type, file_name, s3, project_id, context.op_def.version)
        for file_name, model_type in snapshot_map.items()
    }
    context.log_event(
        dagster.AssetMaterialization(
            asset_key="project_postgres_snapshot",
            description="Avro snapshots of project Postgres data",
            metadata={"project_id": project_id, **deps},
            tags={"owner": JobOwners.TEAM_MAX_AI.value},
        )
    )
    return PostgresProjectDataSnapshot(**deps)


C = TypeVar("C")


@retry(
    retry=retry_if_exception_type(InternalCHQueryError),
    stop=stop_after_attempt(4),
    wait=wait_exponential(min=8),
)
def call_query_runner(callable: Callable[[], C]) -> C:
    return callable()


def snapshot_properties_taxonomy(
    context: dagster.OpExecutionContext,
    s3: S3Resource,
    file_key: str,
    team: Team,
    events: list[TeamTaxonomyItem],
):
    results: list[PropertyTaxonomySnapshot] = []

    def snapshot_event(item: TeamTaxonomyItem):
        return call_query_runner(
            lambda: EventTaxonomyQueryRunner(
                query=EventTaxonomyQuery(event=item.event),
                team=team,
            ).calculate()
        )

    for item in events:
        context.log.info(f"Snapshotting properties taxonomy for event {item.event} of {team.id}")
        results.append(PropertyTaxonomySnapshot(event=item.event, results=snapshot_event(item).results))

    context.log.info(f"Dumping properties taxonomy to {file_key}")
    with dump_model(s3=s3, schema=PropertyTaxonomySnapshot, file_key=file_key) as dump:
        dump(results)


def snapshot_events_taxonomy(
    context: dagster.OpExecutionContext,
    s3: S3Resource,
    team: Team,
    code_version: str | None = None,
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
    with dump_model(s3=s3, schema=TeamTaxonomyItemSnapshot, file_key=events_file_key) as dump:
        dumped_items = TeamTaxonomyItemSnapshot(results=res.results)
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
    context: dagster.OpExecutionContext,
    s3: S3Resource,
    team: Team,
    code_version: str | None = None,
):
    file_key = compose_clickhouse_dump_path(team.id, "actors_property_taxonomy", code_version=code_version)
    if check_dump_exists(s3, file_key):
        context.log.info(f"Skipping actors property taxonomy snapshot for {team.id} because it already exists")
        return file_key

    # Snapshot all group type mappings and person
    results: list[ActorsPropertyTaxonomySnapshot] = []
    group_type_mappings: list[int | None] = [
        None,
        *(g.group_type_index for g in GroupTypeMapping.objects.filter(team=team)),
    ]

    for index in group_type_mappings:
        is_group = index is not None
        log_entity = f"group type {index}" if is_group else "persons"
        context.log.info(f"Snapshotting properties taxonomy for {log_entity}")

        # Retrieve saved property definitions for the group type or person
        property_defs: Iterator[str] = (
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
            for prop, prop_results in zip(batch, cast(list[ActorsPropertyTaxonomyResponse], res.results)):
                results.append(
                    ActorsPropertyTaxonomySnapshot(property=prop, group_type_index=index, results=prop_results)
                )

    context.log.info(f"Dumping actors property taxonomy to {file_key}")
    with dump_model(s3=s3, schema=ActorsPropertyTaxonomySnapshot, file_key=file_key) as dump:
        dump(results)
    return file_key


@dagster.op(
    description="Snapshots ClickHouse project data",
    retry_policy=DEFAULT_RETRY_POLICY,
    tags={
        "owner": JobOwners.TEAM_MAX_AI.value,
        "dagster/max_runtime": 60 * 15,  # 15 minutes
    },
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
            asset_key="project_clickhouse_snapshot",
            description="Avro snapshots of project's ClickHouse queries",
            metadata={
                "project_id": project_id,
                **materialized_result.model_dump(),
            },
            tags={"owner": JobOwners.TEAM_MAX_AI.value},
        )
    )

    return materialized_result
