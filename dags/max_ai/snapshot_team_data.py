from collections.abc import Callable, Iterable, Iterator
from itertools import islice
from typing import TypeVar, cast

import dagster
from dagster_aws.s3.resources import S3Resource
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from posthog.schema import (
    ActorsPropertyTaxonomyQuery,
    ActorsPropertyTaxonomyResponse,
    CachedActorsPropertyTaxonomyQueryResponse,
    CachedEventTaxonomyQueryResponse,
    CachedTeamTaxonomyQueryResponse,
    EventTaxonomyQuery,
    TeamTaxonomyItem,
    TeamTaxonomyQuery,
)

from posthog.hogql.constants import HogQLGlobalSettings

from posthog.clickhouse.client.connection import Workload
from posthog.errors import InternalCHQueryError
from posthog.hogql_queries.ai.actors_property_taxonomy_query_runner import ActorsPropertyTaxonomyQueryRunner
from posthog.hogql_queries.ai.event_taxonomy_query_runner import EventTaxonomyQueryRunner
from posthog.hogql_queries.ai.team_taxonomy_query_runner import TeamTaxonomyQueryRunner
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.models import GroupTypeMapping, Team
from posthog.models.property_definition import PropertyDefinition

from products.enterprise.backend.hogai.eval.schema import (
    ActorsPropertyTaxonomySnapshot,
    BaseSnapshot,
    ClickhouseTeamDataSnapshot,
    DataWarehouseTableSnapshot,
    GroupTypeMappingSnapshot,
    PostgresTeamDataSnapshot,
    PropertyDefinitionSnapshot,
    PropertyTaxonomySnapshot,
    TeamSnapshot,
    TeamTaxonomyItemSnapshot,
)

from dags.common import JobOwners
from dags.max_ai.utils import check_dump_exists, compose_clickhouse_dump_path, compose_postgres_dump_path, dump_model

DEFAULT_RETRY_POLICY = dagster.RetryPolicy(
    max_retries=4,
    delay=2,  # 2 seconds
    backoff=dagster.Backoff.EXPONENTIAL,
    jitter=dagster.Jitter.PLUS_MINUS,
)


SchemaBound = TypeVar("SchemaBound", bound=BaseSnapshot)


class SnapshotUnrecoverableError(ValueError):
    """
    An error that indicates that the snapshot operation cannot be recovered from.
    This is used to indicate that the snapshot operation failed and should not be retried.
    """

    pass


def snapshot_postgres_model(
    context: dagster.OpExecutionContext,
    model_type: type[SchemaBound],
    file_name: str,
    s3: S3Resource,
    team_id: int,
    code_version: str | None = None,
) -> str:
    file_key = compose_postgres_dump_path(team_id, file_name, code_version)
    if check_dump_exists(s3, file_key):
        context.log.info(f"Skipping {file_key} because it already exists")
        return file_key
    context.log.info(f"Dumping {file_key}")
    with dump_model(s3=s3, schema=model_type, file_key=file_key) as dump:
        dump(model_type.serialize_for_team(team_id=team_id))
    return file_key


@dagster.op(
    description="Snapshots Postgres team data (property definitions, DWH schema, etc.)",
    retry_policy=DEFAULT_RETRY_POLICY,
    code_version="v1",
    tags={
        "owner": JobOwners.TEAM_MAX_AI.value,
        "dagster/max_runtime": 60 * 15,  # 15 minutes
    },
)
def snapshot_postgres_team_data(
    context: dagster.OpExecutionContext, team_id: int, s3: S3Resource
) -> PostgresTeamDataSnapshot:
    context.log.info(f"Snapshotting Postgres team data for {team_id}")
    snapshot_map: dict[str, type[BaseSnapshot]] = {
        "team": TeamSnapshot,
        "property_definitions": PropertyDefinitionSnapshot,
        "group_type_mappings": GroupTypeMappingSnapshot,
        "data_warehouse_tables": DataWarehouseTableSnapshot,
    }

    try:
        deps = {
            file_name: snapshot_postgres_model(context, model_type, file_name, s3, team_id, context.op_def.version)
            for file_name, model_type in snapshot_map.items()
        }
        context.log_event(
            dagster.AssetMaterialization(
                asset_key="team_postgres_snapshot",
                description="Avro snapshots of team Postgres data",
                metadata={"team_id": team_id, **deps},
                tags={"owner": JobOwners.TEAM_MAX_AI.value},
            )
        )
    except Team.DoesNotExist as e:
        raise dagster.Failure(
            description=f"Team {team_id} does not exist",
            metadata={"team_id": team_id},
            allow_retries=False,
        ) from e

    return PostgresTeamDataSnapshot(**deps)


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

    def wrapped_query_runner(item: TeamTaxonomyItem):
        response = EventTaxonomyQueryRunner(
            query=EventTaxonomyQuery(event=item.event),
            team=team,
            settings=HogQLGlobalSettings(
                max_execution_time=60 * 5  # 5 minutes
            ),
            workload=Workload.OFFLINE,
        ).run(execution_mode=ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE)
        if not isinstance(response, CachedEventTaxonomyQueryResponse):
            raise SnapshotUnrecoverableError(f"Unexpected response type from event taxonomy query: {type(response)}")
        return response

    def call_event_taxonomy_query(item: TeamTaxonomyItem):
        return call_query_runner(lambda: wrapped_query_runner(item))

    for item in events:
        context.log.info(f"Snapshotting properties taxonomy for event {item.event} of {team.id}")
        results.append(PropertyTaxonomySnapshot(event=item.event, results=call_event_taxonomy_query(item).results))

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

    def snapshot_events_taxonomy():
        response = TeamTaxonomyQueryRunner(
            query=TeamTaxonomyQuery(),
            team=team,
            settings=HogQLGlobalSettings(
                max_execution_time=60 * 5  # 5 minutes
            ),
            workload=Workload.OFFLINE,
        ).run(execution_mode=ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE)
        if not isinstance(response, CachedTeamTaxonomyQueryResponse):
            raise SnapshotUnrecoverableError(f"Unexpected response type from events taxonomy query: {type(response)}")
        return response

    res = call_query_runner(snapshot_events_taxonomy)

    if not res.results:
        raise SnapshotUnrecoverableError("No results from events taxonomy query")

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

            def wrapped_query_runner(index: int | None, batch: list[str]):
                response = ActorsPropertyTaxonomyQueryRunner(
                    query=ActorsPropertyTaxonomyQuery(groupTypeIndex=index, properties=batch, maxPropertyValues=25),
                    team=team,
                    settings=HogQLGlobalSettings(
                        max_execution_time=60 * 5  # 5 minutes
                    ),
                    workload=Workload.OFFLINE,
                ).run(execution_mode=ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE)
                if not isinstance(response, CachedActorsPropertyTaxonomyQueryResponse):
                    raise SnapshotUnrecoverableError(
                        f"Unexpected response type from actors property taxonomy query: {type(response)}"
                    )
                return response

            def call_actors_property_taxonomy_query(index: int | None, batch: list[str]):
                return call_query_runner(lambda: wrapped_query_runner(index, batch))

            res = call_actors_property_taxonomy_query(index, batch)

            if not res.results:
                raise SnapshotUnrecoverableError(
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
    description="Snapshots ClickHouse team data",
    retry_policy=DEFAULT_RETRY_POLICY,
    tags={
        "owner": JobOwners.TEAM_MAX_AI.value,
        "dagster/max_runtime": 60 * 15,  # 15 minutes
    },
    code_version="v1",
)
def snapshot_clickhouse_team_data(
    context: dagster.OpExecutionContext, team_id: int, s3: S3Resource
) -> ClickhouseTeamDataSnapshot:
    try:
        team = Team.objects.get(id=team_id)

    except Team.DoesNotExist as e:
        raise dagster.Failure(
            description=f"Team {team_id} does not exist",
            metadata={"team_id": team_id},
            allow_retries=False,
        ) from e

    try:
        event_taxonomy_file_key, properties_taxonomy_file_key = snapshot_events_taxonomy(
            context, s3, team, context.op_def.version
        )
        actors_property_taxonomy_file_key = snapshot_actors_property_taxonomy(context, s3, team, context.op_def.version)

    except SnapshotUnrecoverableError as e:
        raise dagster.Failure(
            description=f"Error snapshotting team {team_id}",
            metadata={"team_id": team_id},
            allow_retries=False,
        ) from e

    materialized_result = ClickhouseTeamDataSnapshot(
        event_taxonomy=event_taxonomy_file_key,
        properties_taxonomy=properties_taxonomy_file_key,
        actors_property_taxonomy=actors_property_taxonomy_file_key,
    )

    context.log_event(
        dagster.AssetMaterialization(
            asset_key="team_clickhouse_snapshot",
            description="Avro snapshots of team's ClickHouse queries",
            metadata={
                "team_id": team_id,
                **materialized_result.model_dump(),
            },
            tags={"owner": JobOwners.TEAM_MAX_AI.value},
        )
    )

    return materialized_result
