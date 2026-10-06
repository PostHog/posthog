import time
from collections import defaultdict
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import field
from uuid import UUID

from django.conf import settings
from django.db.models import Exists, OuterRef

import structlog
from clickhouse_driver import Client
from clickhouse_driver.errors import Error as ClickHouseDriverError

from posthog.hogql.escape_sql import escape_clickhouse_identifier

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.cluster import TOO_MANY_MUTATIONS, ClickhouseCluster, RetryPolicy, get_cluster
from posthog.dataclasses import frozen
from posthog.models.async_deletion import AsyncDeletion, DeletionType
from posthog.models.deletion_targets import DeletionTarget, UnsweptRowsError, resolve_placements
from posthog.models.person.util import get_person_tombstones
from posthog.models.person_group_membership.sql import (
    DISTRIBUTED_PERSON_GROUP_MEMBERSHIP_CONFIG_TABLE,
    PERSON_GROUP_MEMBERSHIP_CONFIG_TABLE,
    PERSON_GROUP_MEMBERSHIP_TABLE,
    SHARDED_PERSON_GROUP_MEMBERSHIP_TABLE,
)
from posthog.models.team import Team
from posthog.personhog_client.client import personhog_call, require_personhog_client
from posthog.personhog_client.proto import CONSISTENCY_LEVEL_STRONG, GetPersonsByDistinctIdsInTeamRequest, ReadOptions

from products.customer_analytics.backend.facade.membership_deletion_contracts import (
    MembershipDeletionCursor,
    MembershipDeletionDetails,
    MembershipDeletionKind,
)
from products.customer_analytics.backend.logic import membership_deletion_receipts as receipts
from products.customer_analytics.backend.models.membership_deletion import (
    MembershipDeletionReceipt,
    MembershipDeletionTeam,
)

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
# GetPersonsByDistinctIdsInTeamRequest accepts at most 250 distinct IDs.
PAGE_SIZE = 250
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


class MembershipDeletionPending(Exception):
    pass


class MembershipDeletionInterrupted(Exception):
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
            sql=f"SELECT count() FROM {_name(placement.target.read_table)} WHERE {predicate}",
            parameters=parameters,
        )
        survivors = cluster.any_host_by_role(verify, NodeRole.DATA).result()[0][0]
        if survivors:
            raise UnsweptRowsError(f"{placement.target.read_table} keeps {survivors} rows after membership deletion")


def delete_distinct_ids(cluster: ClickhouseCluster, team_id: int, distinct_ids: Sequence[str]) -> None:
    unique = sorted(set(distinct_ids))
    for start in range(0, len(unique), PAGE_SIZE):
        _sweep(
            cluster,
            (MEMBERSHIP_TARGET,),
            "team_id = %(team_id)s AND distinct_id IN %(distinct_ids)s",
            {"team_id": team_id, "distinct_ids": unique[start : start + PAGE_SIZE]},
        )


def delete_teams(cluster: ClickhouseCluster, team_ids: Sequence[int], *, include_config: bool = True) -> None:
    if team_ids:
        targets = (MEMBERSHIP_TARGET, CONFIG_TARGET) if include_config else (MEMBERSHIP_TARGET,)
        _sweep(cluster, targets, "team_id IN %(team_ids)s", {"team_ids": sorted(set(team_ids))})


def _team_distinct_id_pages(cluster: ClickhouseCluster, team_id: int) -> Iterator[list[str]]:
    if not resolve_placements(cluster, (MEMBERSHIP_TARGET,)):
        return
    # Paging in sort key order reads each page from a primary key range instead of rescanning the team.
    after: tuple[object, ...] | None = None
    while True:
        parameters: dict[str, object] = {"team_id": team_id, "limit": PAGE_SIZE}
        resume = ""
        if after is not None:
            resume = " AND (group_type_index, group_key, distinct_id) > %(after)s"
            parameters["after"] = after
        page = _Statement(
            operation="page",
            sql=f"SELECT group_type_index, group_key, distinct_id FROM {_name(MEMBERSHIP_TARGET.read_table)} "
            f"WHERE team_id = %(team_id)s{resume} ORDER BY group_type_index, group_key, distinct_id LIMIT %(limit)s",
            parameters=parameters,
        )
        rows = cluster.any_host_by_role(page, NodeRole.DATA).result()
        if rows:
            yield sorted({str(row[2]) for row in rows})
        if len(rows) < PAGE_SIZE:
            return
        after = rows[-1]


def _actively_owned(team_id: int, distinct_ids: Sequence[str]) -> set[str]:
    def lookup() -> set[str]:
        response = require_personhog_client().get_persons_by_distinct_ids_in_team(
            GetPersonsByDistinctIdsInTeamRequest(
                team_id=team_id, distinct_ids=list(distinct_ids), read_options=_OWNER_READ_OPTIONS
            )
        )
        return {
            result.distinct_id
            for result in response.results
            if result.HasField("person") and result.person.id and result.person.team_id == team_id
        }

    return personhog_call("membership_deletion_active_owners", lookup)


def _delete_unowned(cluster: ClickhouseCluster, team_id: int, distinct_ids: Sequence[str]) -> None:
    # A live owner holds the distinct ID again, so its membership rows are no longer the deleted person's.
    if distinct_ids:
        owned = _actively_owned(team_id, distinct_ids)
        delete_distinct_ids(cluster, team_id, [distinct_id for distinct_id in distinct_ids if distinct_id not in owned])


def team_deletion_verified(team_id: int) -> bool:
    if Team.objects.filter(id=team_id).exists():
        return False
    if AsyncDeletion.objects.filter(deletion_type=DeletionType.Team, team_id=team_id).exists():
        return True
    return (
        MembershipDeletionReceipt.objects.for_team(team_id)
        .filter(
            kind=MembershipDeletionKind.TEAM,
            source_key=f"team_record:{team_id}",
            confirmed_at__isnull=False,
        )
        .exists()
    )


def process_membership_deletion(
    cluster: ClickhouseCluster,
    team_id: int,
    receipt_id: UUID,
    *,
    after_id: int = 0,
    on_page: Callable[[int], None] = lambda _cursor: None,
    should_stop: Callable[[], bool] = lambda: False,
) -> None:
    details = receipts.get_membership_deletion(team_id, receipt_id)
    if details.completed:
        return
    if not details.confirmed:
        raise MembershipDeletionPending("Membership deletion is not confirmed")
    if details.kind == MembershipDeletionKind.TEAM:
        if not team_deletion_verified(team_id):
            raise MembershipDeletionPending("Team deletion is not verified")
        delete_teams(cluster, [team_id], include_config=True)
    elif details.kind == MembershipDeletionKind.TEAM_PERSONS:
        for distinct_ids in _team_distinct_id_pages(cluster, team_id):
            if should_stop():
                raise MembershipDeletionInterrupted()
            _delete_unowned(cluster, team_id, distinct_ids)
    else:
        cursor: int | None = after_id
        while cursor is not None:
            if should_stop():
                raise MembershipDeletionInterrupted()
            page = receipts.list_membership_deletion_identities(team_id, receipt_id, after_id=cursor, limit=PAGE_SIZE)
            _delete_unowned(cluster, team_id, [row.identity.distinct_id for row in page.identities])
            cursor = page.next_cursor
            if cursor is not None:
                on_page(cursor)
    receipts.complete_membership_deletion(team_id, receipt_id)


def discover_team_deletions(after_id: int) -> int | None:
    registered = MembershipDeletionTeam.objects.unscoped().filter(team_id=OuterRef("team_id"))
    prepared = MembershipDeletionReceipt.objects.unscoped().filter(
        team_id=OuterRef("team_id"), kind=MembershipDeletionKind.TEAM.value
    )
    rows = list(
        AsyncDeletion.objects.filter(deletion_type=DeletionType.Team, id__gt=after_id)
        .filter(Exists(registered))
        .exclude(Exists(prepared))
        .exclude(Exists(Team.objects.filter(id=OuterRef("team_id"))))
        .order_by("id")
        .values_list("id", "team_id")[:PAGE_SIZE]
    )
    for deletion_id, team_id in rows:
        try:
            receipt_id = receipts.prepare_membership_deletion(
                team_id, MembershipDeletionKind.TEAM, f"async_deletion:{deletion_id}"
            )
            receipts.confirm_membership_deletion(team_id, receipt_id)
        except Exception as error:
            logger.warning("membership_team_discovery_failed", team_id=team_id, error_type=type(error).__name__)
    return rows[-1][0] if len(rows) == PAGE_SIZE else None


def _record_tombstones(team_id: int, prepared: Sequence[MembershipDeletionDetails]) -> None:
    uuids = [details.person_uuid for details in prepared if details.person_uuid is not None]
    tombstones = {tombstone.uuid: tombstone for tombstone in get_person_tombstones(team_id, uuids)}
    for details in prepared:
        # Only a committed tombstone proves erasure. A missing person can still be in the middle of its deletion.
        tombstone = tombstones.get(details.person_uuid) if details.person_uuid is not None else None
        if tombstone is not None:
            try:
                receipts.record_person_membership_deletion(team_id, details.source_key, tombstone)
            except Exception as error:
                logger.warning(
                    "membership_tombstone_record_failed", receipt_id=str(details.id), error_type=type(error).__name__
                )


def recover_prepared_deletions(after: MembershipDeletionCursor | None) -> MembershipDeletionCursor | None:
    page = receipts.list_pending_preparations(after=after, limit=PAGE_SIZE)
    people: dict[int, list[MembershipDeletionDetails]] = defaultdict(list)
    for reference in page.receipts:
        try:
            if reference.kind == MembershipDeletionKind.PERSON:
                people[reference.team_id].append(receipts.get_membership_deletion(reference.team_id, reference.id))
            elif reference.kind == MembershipDeletionKind.TEAM and team_deletion_verified(reference.team_id):
                receipts.confirm_membership_deletion(reference.team_id, reference.id)
        except Exception as error:
            logger.warning("membership_recovery_failed", receipt_id=str(reference.id), error_type=type(error).__name__)
    for team_id, prepared in people.items():
        try:
            _record_tombstones(team_id, prepared)
        except Exception as error:
            logger.warning("membership_tombstone_lookup_failed", team_id=team_id, error_type=type(error).__name__)
    return page.next_cursor
