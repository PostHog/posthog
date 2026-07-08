"""Helpers for applying event deletions and mutations to every physical events table.

While the legacy String-properties events table and the native-JSON events table coexist
(dual-write via ``events_json_table_mv``), every delete or mutation applied to
``sharded_events`` must also be applied to ``sharded_events_json`` — otherwise the two tables
diverge and deleted data survives in whichever table serves queries. The JSON tables are only
targeted where they exist, so environments that have not run the ``0287_events_json_schema``
migration (and legacy-schema test databases) keep working unchanged.
"""

from functools import partial

from django.conf import settings

from clickhouse_driver import Client

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.cluster import ClickhouseCluster
from posthog.models.event.sql import DISTRIBUTED_EVENTS_JSON_TABLE, EVENTS_DATA_TABLE, EVENTS_JSON_DATA_TABLE


def _table_exists(client: Client, table: str) -> bool:
    [[count]] = client.execute(
        "SELECT count() FROM system.tables WHERE database = %(database)s AND name = %(name)s",
        {"database": settings.CLICKHOUSE_DATABASE, "name": table},
    )
    return bool(count)


def _table_exists_via_sync_execute(table: str) -> bool:
    result = sync_execute(
        "SELECT count() FROM system.tables WHERE database = %(database)s AND name = %(name)s",
        {"database": settings.CLICKHOUSE_DATABASE, "name": table},
    )
    return bool(result and result[0][0])


def cluster_has_events_json_table(cluster: ClickhouseCluster) -> bool:
    """Whether any data node carries the native-JSON events data table.

    ``any`` rather than ``all``: on a partially-migrated cluster the follow-up mutation fails
    loudly on the hosts missing the table, which is preferable to silently skipping a deletion.
    """
    results = cluster.map_hosts_by_role(partial(_table_exists, table=EVENTS_JSON_DATA_TABLE), NodeRole.DATA).result()
    return any(results.values())


def events_data_tables(cluster: ClickhouseCluster) -> list[str]:
    """The physical events data tables that deletions/mutations must target, for Dagster jobs."""
    tables = [EVENTS_DATA_TABLE()]
    if cluster_has_events_json_table(cluster):
        tables.append(EVENTS_JSON_DATA_TABLE)
    return tables


def events_data_tables_via_sync_execute() -> list[str]:
    """Like ``events_data_tables``, for callers that talk to ClickHouse through ``sync_execute``."""
    tables = [EVENTS_DATA_TABLE()]
    if _table_exists_via_sync_execute(EVENTS_JSON_DATA_TABLE):
        tables.append(EVENTS_JSON_DATA_TABLE)
    return tables


def events_read_tables_via_sync_execute() -> list[str]:
    """The distributed events read tables to check when verifying that a deletion completed."""
    tables = ["events"]
    if _table_exists_via_sync_execute(DISTRIBUTED_EVENTS_JSON_TABLE):
        tables.append(DISTRIBUTED_EVENTS_JSON_TABLE)
    return tables
