import time
from collections.abc import Mapping, Sequence
from dataclasses import field
from typing import cast

from django.conf import settings

import structlog
from clickhouse_driver import Client
from clickhouse_driver.errors import Error as ClickHouseDriverError

from posthog.hogql.escape_sql import escape_clickhouse_identifier

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.cluster import TOO_MANY_MUTATIONS, ClickhouseCluster, RetryPolicy, get_cluster
from posthog.dataclasses import frozen
from posthog.models.deletion_targets import DeletionTarget, UnsweptRowsError, resolve_placements, surviving_rows_sql
from posthog.models.person_group_membership.sql import (
    DISTRIBUTED_PERSON_GROUP_MEMBERSHIP_CONFIG_TABLE,
    PERSON_GROUP_MEMBERSHIP_CONFIG_TABLE,
    PERSON_GROUP_MEMBERSHIP_TABLE,
    SHARDED_PERSON_GROUP_MEMBERSHIP_TABLE,
)
from posthog.personhog_client.client import personhog_call, require_personhog_client
from posthog.personhog_client.proto import CONSISTENCY_LEVEL_STRONG, GetPersonsByDistinctIdsInTeamRequest, ReadOptions

logger = structlog.get_logger(__name__)

MEMBERSHIP_TARGET = DeletionTarget(
    data_table=SHARDED_PERSON_GROUP_MEMBERSHIP_TABLE,
    read_table=PERSON_GROUP_MEMBERSHIP_TABLE,
    cluster_setting="CLICKHOUSE_AUX_CLUSTER",
    node_role=NodeRole.AUX,
    optional=True,
    stores_person_properties=False,
)
CONFIG_TARGET = DeletionTarget(
    data_table=PERSON_GROUP_MEMBERSHIP_CONFIG_TABLE,
    read_table=DISTRIBUTED_PERSON_GROUP_MEMBERSHIP_CONFIG_TABLE,
    cluster_setting="CLICKHOUSE_AUX_CLUSTER",
    node_role=NodeRole.AUX,
    optional=True,
    stores_person_properties=False,
)
# GetPersonsByDistinctIdsInTeamRequest accepts at most 250 distinct IDs. A distinct ID can hold 400 characters
# and the driver inlines parameters into the query text, so 250 IDs also stay below ClickHouse's default
# max_query_size of 256 KiB.
DISTINCT_ID_CHUNK_SIZE = 250
QUERY_SETTINGS: Mapping[str, str] = {"max_execution_time": "60"}
DELETE_SETTINGS: Mapping[str, str] = {**QUERY_SETTINGS, "lightweight_deletes_sync": "2", "mutations_sync": "2"}
CAPACITY_WAIT_SECONDS = 120.0
CAPACITY_POLL_SECONDS = 5.0
_OWNER_READ_OPTIONS = ReadOptions(consistency=CONSISTENCY_LEVEL_STRONG, field_mask=["id", "uuid", "team_id"])


class MembershipClickHouseError(Exception):
    """Keeps only the operation and error code, because ClickHouse messages can echo bound distinct IDs."""

    def __init__(self, operation: str, code: int | None) -> None:
        super().__init__(f"Membership {operation} failed with ClickHouse error code {code}")
        self.operation = operation
        self.code = code


class MembershipCapacityError(Exception):
    pass


def membership_cluster() -> ClickhouseCluster:
    return get_cluster(
        client_settings=QUERY_SETTINGS,
        connection_overrides={"connect_timeout": 5, "send_receive_timeout": 30, "sync_request_timeout": 5},
        retry_policy=RetryPolicy(max_attempts=2, delay=2.0, exceptions=(MembershipClickHouseError,)),
    )


def _name(table: str) -> str:
    return escape_clickhouse_identifier(settings.CLICKHOUSE_DATABASE) + "." + escape_clickhouse_identifier(table)


def _run(
    client: Client, operation: str, sql: str, parameters: Mapping[str, object], query_settings: Mapping[str, str]
) -> list[tuple[object, ...]]:
    try:
        rows: list[tuple[object, ...]] = client.execute(sql, dict(parameters), settings=dict(query_settings))
        return rows
    except Exception as error:
        code: int | None = error.code if isinstance(error, ClickHouseDriverError) else None
    # Raised outside the handler so the original exception and its message never become the context.
    raise MembershipClickHouseError(operation, code)


# ClickhouseCluster and RetryPolicy log tasks with %r, so parameters stay out of every repr.
@frozen
class _Statement:
    operation: str
    sql: str
    parameters: Mapping[str, object] = field(repr=False)

    def __call__(self, client: Client) -> list[tuple[object, ...]]:
        return _run(client, self.operation, self.sql, self.parameters, QUERY_SETTINGS)


@frozen
class _Delete:
    table: str
    predicate: str
    parameters: Mapping[str, object] = field(repr=False)

    def __call__(self, client: Client) -> None:
        # A delete queued behind another mutation outlives the socket timeout and each retry queues one more.
        deadline = time.monotonic() + CAPACITY_WAIT_SECONDS
        busy = {"database": settings.CLICKHOUSE_DATABASE, "table": self.table}
        while True:
            pending = _run(
                client,
                "capacity check",
                "SELECT count() FROM system.mutations "
                "WHERE database = %(database)s AND table = %(table)s AND NOT is_done AND NOT is_killed",
                busy,
                QUERY_SETTINGS,
            )
            if not pending[0][0]:
                try:
                    _run(
                        client,
                        "delete",
                        f"DELETE FROM {_name(self.table)} WHERE {self.predicate}",
                        self.parameters,
                        DELETE_SETTINGS,
                    )
                    return
                except MembershipClickHouseError as error:
                    if error.code != TOO_MANY_MUTATIONS:
                        raise
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise MembershipCapacityError(f"{self.table} has no mutation capacity")
            time.sleep(min(CAPACITY_POLL_SECONDS, remaining))


def _sweep(
    cluster: ClickhouseCluster, targets: Sequence[DeletionTarget], predicate: str, parameters: Mapping[str, object]
) -> None:
    for placement in resolve_placements(cluster, targets):
        delete = _Delete(table=placement.target.data_table, predicate=predicate, parameters=parameters)
        placement.cluster.map_one_host_per_shard(delete).result()
        verify = _Statement(
            operation="verification",
            sql=surviving_rows_sql(_name(placement.target.read_table), predicate),
            parameters=parameters,
        )
        survivors = cluster.any_host_by_role(verify, NodeRole.DATA).result()[0][0]
        if survivors:
            raise UnsweptRowsError(f"{placement.target.read_table} keeps {survivors} rows after membership deletion")


def delete_distinct_ids(cluster: ClickhouseCluster, team_id: int, distinct_ids: Sequence[str]) -> None:
    unique = sorted(set(distinct_ids))
    for start in range(0, len(unique), DISTINCT_ID_CHUNK_SIZE):
        _sweep(
            cluster,
            (MEMBERSHIP_TARGET,),
            "team_id = %(team_id)s AND distinct_id IN %(distinct_ids)s",
            {"team_id": team_id, "distinct_ids": unique[start : start + DISTINCT_ID_CHUNK_SIZE]},
        )


def delete_teams(cluster: ClickhouseCluster, team_ids: Sequence[int]) -> None:
    if team_ids:
        _sweep(
            cluster, (MEMBERSHIP_TARGET, CONFIG_TARGET), "team_id IN %(team_ids)s", {"team_ids": sorted(set(team_ids))}
        )


def team_has_membership(cluster: ClickhouseCluster, team_id: int) -> bool:
    """Missing optional tables return False, so their work completes. An unreachable populated table raises."""
    if not resolve_placements(cluster, (MEMBERSHIP_TARGET,)):
        return False
    probe = _Statement(
        operation="probe",
        sql=f"SELECT 1 FROM {_name(MEMBERSHIP_TARGET.read_table)} WHERE team_id = %(team_id)s LIMIT 1",
        parameters={"team_id": team_id},
    )
    return bool(cluster.any_host_by_role(probe, NodeRole.DATA).result())


def stored_team_ids(cluster: ClickhouseCluster, *, after: int, limit: int) -> tuple[list[int], int | None]:
    pages: list[list[int]] = []
    for placement in resolve_placements(cluster, (MEMBERSHIP_TARGET, CONFIG_TARGET)):
        page = _Statement(
            operation="team scan",
            sql=f"SELECT DISTINCT team_id FROM {_name(placement.target.read_table)} "
            "WHERE team_id > %(after)s ORDER BY team_id LIMIT %(limit)s",
            parameters={"after": after, "limit": limit},
        )
        pages.append([cast(int, row[0]) for row in cluster.any_host_by_role(page, NodeRole.DATA).result()])
    # Every source page holds all its IDs up to its own last one, so the merged first `limit` IDs miss none.
    merged = sorted({team_id for page in pages for team_id in page})
    if len(merged) < limit:
        return merged, None
    return merged[:limit], merged[limit - 1]


def actively_owned(team_id: int, distinct_ids: Sequence[str]) -> set[str]:
    """The lookup is not fenced against a reassignment that commits before the delete runs."""
    owned: set[str] = set()
    for start in range(0, len(distinct_ids), DISTINCT_ID_CHUNK_SIZE):
        chunk = list(distinct_ids[start : start + DISTINCT_ID_CHUNK_SIZE])

        def lookup(chunk: list[str] = chunk) -> set[str]:
            response = require_personhog_client().get_persons_by_distinct_ids_in_team(
                GetPersonsByDistinctIdsInTeamRequest(
                    team_id=team_id, distinct_ids=chunk, read_options=_OWNER_READ_OPTIONS
                )
            )
            return {
                result.distinct_id
                for result in response.results
                if result.HasField("person") and result.person.id and result.person.team_id == team_id
            }

        owned |= personhog_call("membership_deletion_active_owners", lookup)
    return owned
