"""Helpers for applying event deletions and mutations to every physical events table.

While the legacy String-properties events table and the native-JSON events table coexist
(dual-write via ``events_json_table_mv``), every delete or mutation applied to
``sharded_events`` must also be applied to ``sharded_events_json`` — otherwise the two tables
diverge and deleted data survives in whichever table serves queries. The JSON tables are only
targeted where they exist, so environments that have not run the ``0288_events_json_schema``
migration (and legacy-schema test databases) keep working unchanged.

These are the events tables specifically. A deletion that must reach every table carrying person
data — person removal, team deletion, the queued-uuid drain — wants
``posthog.models.deletion_targets.personal_data_tables`` instead.
"""

from posthog.clickhouse.cluster import ClickhouseCluster
from posthog.models.deletion_targets import (
    EVENTS_JSON,
    EVENTS_TARGETS,
    dispatchable_here,
    resolve_data_targets_via_sync_execute,
    resolve_read_targets_via_sync_execute,
    resolve_targets_here,
)


def cluster_has_events_json_table(cluster: ClickhouseCluster) -> bool:
    """Whether this handle's own data nodes carry the native-JSON events data table.

    Refuses rather than answering False when another cluster's do; see ``dispatchable_here``.
    """
    return dispatchable_here(cluster, EVENTS_JSON)


def events_data_tables(cluster: ClickhouseCluster) -> list[str]:
    """The physical events data tables that deletions/mutations must target, for Dagster jobs."""
    return [target.data_table for target in resolve_targets_here(cluster, EVENTS_TARGETS)]


def events_data_tables_via_sync_execute() -> list[str]:
    """Like ``events_data_tables``, for callers that talk to ClickHouse through ``sync_execute``."""
    return [target.data_table for target in resolve_data_targets_via_sync_execute(EVENTS_TARGETS)]


def events_read_tables_via_sync_execute() -> list[str]:
    """The distributed events read tables to check when verifying that a deletion completed."""
    return [target.read_table for target in resolve_read_targets_via_sync_execute(EVENTS_TARGETS)]
