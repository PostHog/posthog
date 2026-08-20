"""Which physical ClickHouse tables a data deletion has to sweep.

Erasing a person's data is not a property of the events table — it is a property of every table
that stores rows attributable to a person. This module is the one list of those tables, so a table
that starts carrying person data gets registered here rather than found by an auditor months later.

Every target is swept with predicates built only from columns all of them declare: ``team_id``,
``person_id``, ``distinct_id``, ``timestamp``, ``uuid``, ``event``.

The reasoning behind each registration, exclusion and known gap is in
docs/internal/clickhouse-deletion-coverage.md.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from functools import partial

from django.conf import settings

from clickhouse_driver import Client

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.cluster import ClickhouseCluster, Query
from posthog.models.event.sql import (
    DISTRIBUTED_EVENTS_JSON_TABLE,
    EVENTS_DATA_TABLE,
    EVENTS_JSON_DATA_TABLE,
    SHARDED_EVENTS_RECENT_DATA_TABLE,
)
from posthog.models.flag_evaluations.sql import (
    FLAG_EVALUATIONS_DATA_TABLE,
    FLAG_EVALUATIONS_SOURCE_EVENT,
    FLAG_EVALUATIONS_TABLE,
)


class UnsweepableRowsError(Exception):
    """A deletion would report success while rows it cannot reach survive on another table."""


class HogQLSchema(Enum):
    """Which schema a compiled HogQL predicate must target to run against a table."""

    LEGACY = "legacy"
    NATIVE_JSON = "native_json"


@dataclass(frozen=True, kw_only=True)
class DeletionTarget:
    """One physical table a deletion sweep runs against.

    ``data_table`` is the local per-shard storage table a mutation is issued on; ``read_table`` is
    the Distributed proxy a verification count reads through.

    The capability fields exist so a caller needing more than the schema-agnostic predicates fails
    loudly on a table that cannot take it, rather than skipping it silently.
    """

    data_table: str
    read_table: str
    # Guarded on system.tables: the table sits behind a migration that may not have run everywhere.
    optional: bool = False
    # The schema a HogQL predicate compiles against here, None where no HogQL table definition
    # exists. A compiled fragment names physical columns (mat_*, the property-group maps, or JSON
    # subcolumns), so it only runs against the schema it was compiled for.
    hogql_schema: HogQLSchema | None = None
    # properties/person_properties can be rewritten in place. True needs both halves: the property
    # columns are DEFAULT-kind (assignable by ALTER UPDATE, as materialize() mints them), and the
    # property-rewrite machinery in posthog/dags/data_deletion_requests.py actually sweeps the
    # table, which today is hardcoded to the events tables. flag_evaluations satisfies only the
    # schema half, so flipping this without extending the sweep silently under-deletes.
    accepts_property_rewrite: bool = False
    # Read uuids from this table when queueing a deferred deletion. False where the rows duplicate
    # another target's uuids, which would queue each one twice.
    queue_uuid_candidates: bool = True
    # The event names this table can hold, None meaning unconstrained. Lets a request naming other
    # events skip this table without querying it.
    stored_events: frozenset[str] | None = None

    @property
    def accepts_hogql_predicate(self) -> bool:
        return self.hogql_schema is not None

    @property
    def uses_new_events_schema(self) -> bool:
        return self.hogql_schema is HogQLSchema.NATIVE_JSON

    def may_hold_any_of(self, events: Sequence[str]) -> bool:
        """Whether this table could hold rows for any of ``events``, empty meaning every event.

        A request naming only events a table never stores can skip it, which matters because
        counting to prove zero is not free: no target indexes ``event``, so the query reads the
        team's rows across whichever partitions the request's time range covers.
        """
        if not events or self.stored_events is None:
            return True
        return not self.stored_events.isdisjoint(events)


EVENTS = DeletionTarget(
    data_table=EVENTS_DATA_TABLE(),
    read_table="events",
    hogql_schema=HogQLSchema.LEGACY,
    accepts_property_rewrite=True,
)

EVENTS_JSON = DeletionTarget(
    data_table=EVENTS_JSON_DATA_TABLE,
    read_table=DISTRIBUTED_EVENTS_JSON_TABLE,
    optional=True,
    hogql_schema=HogQLSchema.NATIVE_JSON,
    accepts_property_rewrite=True,
    # Dual-written from the same events, so its uuids are the legacy table's.
    queue_uuid_candidates=False,
)

# Flag-evaluation telemetry carries the same person and group payload as events, so person, team
# and queued-uuid sweeps must reach it. It takes neither of the richer sweeps; both exclusions are
# explained in docs/internal/clickhouse-deletion-coverage.md. Its producer populates person_id
# exactly as the events pipeline does, so a person sweep matches on person_id like every other
# events-shaped table.
FLAG_EVALUATIONS = DeletionTarget(
    data_table=FLAG_EVALUATIONS_DATA_TABLE,
    read_table=FLAG_EVALUATIONS_TABLE,
    optional=True,
    stored_events=frozenset({FLAG_EVALUATIONS_SOURCE_EVENT}),
)

EVENTS_TARGETS: tuple[DeletionTarget, ...] = (EVENTS, EVENTS_JSON)
PERSONAL_DATA_TARGETS: tuple[DeletionTarget, ...] = (*EVENTS_TARGETS, FLAG_EVALUATIONS)

# Storage tables that carry person properties and are reclaimed by their TTL alone. Each entry is a
# decision that erasure may lag by the retention window, not an oversight.
#
# sharded_events_recent is a transient mirror of the last few days of events, on a 7-day TTL keyed
# on inserted_at. Seven days is a short enough window to accept as the erasure bound, and a sweep
# would race the TTL for little benefit.
TTL_ONLY_TABLES: frozenset[str] = frozenset({SHARDED_EVENTS_RECENT_DATA_TABLE()})


_TABLE_EXISTS_SQL = "SELECT count() FROM system.tables WHERE database = %(database)s AND name = %(name)s"


def _table_exists_params(table: str) -> dict[str, str]:
    return {"database": settings.CLICKHOUSE_DATABASE, "name": table}


def _table_exists(client: Client, table: str) -> bool:
    [[count]] = client.execute(_TABLE_EXISTS_SQL, _table_exists_params(table))
    return bool(count)


def _table_exists_via_sync_execute(table: str) -> bool:
    result = sync_execute(_TABLE_EXISTS_SQL, _table_exists_params(table))
    return bool(result and result[0][0])


def is_present(cluster: ClickhouseCluster, target: DeletionTarget) -> bool:
    """Whether any data node carries this target's storage table.

    ``any`` rather than ``all``: on a partially-migrated cluster the mutation fails loudly on the
    hosts missing the table, which is preferable to silently skipping a deletion.
    """
    if not target.optional:
        return True
    results = cluster.map_hosts_by_role(partial(_table_exists, table=target.data_table), NodeRole.DATA).result()
    return any(results.values())


def resolve_targets(
    cluster: ClickhouseCluster, targets: Sequence[DeletionTarget] = PERSONAL_DATA_TARGETS
) -> list[DeletionTarget]:
    """The subset of ``targets`` that actually exists on this cluster."""
    return [target for target in targets if is_present(cluster, target)]


def personal_data_tables(cluster: ClickhouseCluster) -> list[str]:
    """Every physical table a person, team, or queued-uuid deletion must sweep."""
    return [target.data_table for target in resolve_targets(cluster)]


def resolve_data_targets_via_sync_execute(targets: Sequence[DeletionTarget]) -> list[DeletionTarget]:
    """Targets whose storage table exists, for callers talking to ClickHouse via ``sync_execute``."""
    return [target for target in targets if not target.optional or _table_exists_via_sync_execute(target.data_table)]


def resolve_read_targets_via_sync_execute(
    targets: Sequence[DeletionTarget] = PERSONAL_DATA_TARGETS,
) -> list[DeletionTarget]:
    """Targets whose Distributed read table exists, for callers verifying a deletion completed."""
    return [target for target in targets if not target.optional or _table_exists_via_sync_execute(target.read_table)]


def surviving_rows_sql(read_table: str, predicate: str) -> str:
    """Count rows still matching ``predicate``, excluding ones a lightweight delete already hid.

    ``_row_exists = 1`` is what makes this a survivor count rather than a row count; without it
    every deleted row still reads as present until its parts merge.
    """
    # nosemgrep: clickhouse-fstring-param-audit (predicate built from internal helpers, not user input)
    return f"SELECT count() FROM {read_table} WHERE {predicate} AND _row_exists = 1"


def assert_no_unsweepable_rows(
    cluster: ClickhouseCluster,
    targets: Sequence[DeletionTarget],
    predicate: str,
    params: dict,
    *,
    events: Sequence[str],
    reason: str,
) -> None:
    """Fail when a target this request cannot sweep actually holds rows matching it.

    Pass targets already narrowed by ``resolve_targets``; this does not re-check presence.

    ``predicate`` must be the portable part of the criteria — no HogQL fragment, no
    materialized-column arms — so the count is a superset of what the deletion would have removed.
    ``events`` is the request's event filter, empty meaning every event.

    Deliberately gated on rows existing rather than on the request's shape: an unconditional
    refusal would block every request of that shape from the day it lands, including the ones with
    nothing to strand.
    """
    for target in targets:
        if not target.may_hold_any_of(events):
            continue

        # Read through the Distributed proxy on a data node — these tables exist on no other role.
        # Bounded like the job's other scans: no target indexes `event`, so this reads the team's
        # rows across the request's partitions once the table is no longer empty.
        query = Query(surviving_rows_sql(target.read_table, predicate), params, settings={"max_execution_time": "1800"})
        rows = cluster.any_host_by_role(query, NodeRole.DATA).result()
        count = int(rows[0][0]) if rows else 0
        if count:
            raise UnsweepableRowsError(
                f"{count} row(s) in {target.read_table} match this request but cannot be deleted: {reason}"
            )
