"""ClickHouse schema for the dmat slot-assignments dictionary.

The weekly dmat backfill workflow writes the current `(team_id, column_index) →
property_name` mapping into `dmat_slot_assignments` on the **data** cluster, then
reloads the `dmat_slot_assignments_dict` dictionary. The backfill mutation (on the
data cluster) and the live events MV (on the ingestion-events cluster) both read the
mapping via `dictGetString` / `dictHas`, which keeps both paths constant-size
regardless of how many teams have adopted dmat.

Why the table lives only on the data cluster
---------------------------------------------
The table is a `ReplicatedReplacingMergeTree` on the **data** role only (stable EC2,
persistent storage, not autoscaled). The ingestion-events pods do NOT hold a local
copy; their dictionary sources the mapping **remotely** from the data cluster via a
named collection. A freshly-started ingestion pod therefore loads the *complete*
current snapshot (or its `dictGet` throws and ingestion blocks — fail-closed), rather
than loading from a still-syncing local replica and silently emitting NULLs. See
`DMAT_SLOT_ASSIGNMENTS_DICTIONARY_SQL`.

Why a `generation` column instead of TRUNCATE+INSERT
----------------------------------------------------
Each weekly run inserts a full snapshot tagged with a new monotonic `generation`, and
every dictionary query reads only `generation = (SELECT max(generation) …)`. This:
  * makes the swap **atomic** — readers see the previous complete generation until the
    new one's part lands, never an empty/partial table (a `TRUNCATE` replicates with a
    gap before the following `INSERT`, briefly emptying the table for remote readers);
  * handles deletions for free — a slot dropped this cycle is simply absent from the
    new generation, so it disappears without needing tombstones.
Old generations are pruned after a successful reload.
"""

from django.conf import settings

from posthog.clickhouse.cluster import ON_CLUSTER_CLAUSE
from posthog.clickhouse.table_engines import ReplacingMergeTree, ReplicationScheme
from posthog.settings.data_stores import CLICKHOUSE_DATABASE, CLICKHOUSE_PASSWORD, CLICKHOUSE_USER

DMAT_SLOT_ASSIGNMENTS_TABLE_NAME = "dmat_slot_assignments"
DMAT_SLOT_ASSIGNMENTS_DICTIONARY_NAME = "dmat_slot_assignments_dict"

# ZooKeeper path key for the data-cluster replica set. The table only ever exists on the
# data role, so a single fixed key is enough; tests ignore it (the engine substitutes a
# unique path so repeated runs don't collide in ZooKeeper).
_DATA_ZK_PATH_KEY = "data"


def DMAT_SLOT_ASSIGNMENTS_TABLE_SQL(on_cluster: bool = False) -> str:
    # ReplicatedReplacingMergeTree on the data cluster: a single write replicates to every
    # data node, so any data node can serve the dictionary's source query with a complete
    # copy. `generation` lets multiple full snapshots coexist; the dictionary reads only the
    # latest (see DMAT_SLOT_ASSIGNMENTS_DICTIONARY_QUERY). ORDER BY ends with `generation` so
    # snapshots don't collapse into each other while ReplacingMergeTree still dedupes retries
    # of the same (team, column, generation) by `version`.
    engine = ReplacingMergeTree(
        DMAT_SLOT_ASSIGNMENTS_TABLE_NAME,
        replication_scheme=ReplicationScheme.REPLICATED,
        ver="version",
    )
    if not settings.TEST:
        engine.set_zookeeper_path_key(_DATA_ZK_PATH_KEY)
    return """
CREATE TABLE IF NOT EXISTS {table_name} {on_cluster_clause} (
    team_id UInt64,
    column_index UInt8,
    property_name String,
    generation UInt64,
    version UInt32 DEFAULT toUnixTimestamp(now())
) ENGINE = {engine}
ORDER BY (team_id, column_index, generation);
""".format(
        on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster),
        table_name=f"`{DMAT_SLOT_ASSIGNMENTS_TABLE_NAME}`",
        engine=engine,
    )


def DMAT_SLOT_ASSIGNMENTS_DICTIONARY_QUERY() -> str:
    # Read only the latest fully-written snapshot. The `generation = (SELECT max(...))`
    # filter is what makes the weekly swap atomic for readers and drops slots removed this
    # cycle. FINAL collapses any un-merged ReplacingMergeTree duplicates within that
    # generation (e.g. a retried insert) before they reach the dictionary.
    return f"""
SELECT
    team_id,
    column_index,
    property_name
FROM
    `{CLICKHOUSE_DATABASE}`.`{DMAT_SLOT_ASSIGNMENTS_TABLE_NAME}`
FINAL
WHERE generation = (SELECT max(generation) FROM `{CLICKHOUSE_DATABASE}`.`{DMAT_SLOT_ASSIGNMENTS_TABLE_NAME}`)
""".replace("\n", " ").strip()


def DMAT_SLOT_ASSIGNMENTS_DICTIONARY_SQL(on_cluster: bool = False, remote_named_collection: str | None = None) -> str:
    """Create the slot-assignments dictionary.

    With `remote_named_collection` set (the ingestion-events cluster), the source reads the
    table on the **data** cluster through that named collection — so a fresh ingestion pod
    loads the complete snapshot from the stable data cluster, or `dictGet` throws and the
    insert (hence Kafka block) fails closed. Without it (the data cluster itself, and
    single-node/test installs), the source reads the local table.
    """
    if remote_named_collection:
        source = f"SOURCE(CLICKHOUSE(NAME '{remote_named_collection}' QUERY '{DMAT_SLOT_ASSIGNMENTS_DICTIONARY_QUERY()}'))"
    else:
        source = (
            "SOURCE(CLICKHOUSE("
            f"QUERY '{DMAT_SLOT_ASSIGNMENTS_DICTIONARY_QUERY()}' "
            f"USER '{CLICKHOUSE_USER}' PASSWORD '{CLICKHOUSE_PASSWORD}'))"
        )
    return """
CREATE DICTIONARY IF NOT EXISTS {dictionary_name} {on_cluster_clause} (
    team_id UInt64,
    column_index UInt8,
    property_name String
)
PRIMARY KEY team_id, column_index
{source}
LIFETIME(MIN 600 MAX 1200)
LAYOUT(COMPLEX_KEY_HASHED())""".format(
        dictionary_name=f"`{DMAT_SLOT_ASSIGNMENTS_DICTIONARY_NAME}`",
        on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster),
        source=source,
    )


def DROP_DMAT_SLOT_ASSIGNMENTS_DICTIONARY_SQL(on_cluster: bool = False) -> str:
    return (
        f"DROP DICTIONARY IF EXISTS `{DMAT_SLOT_ASSIGNMENTS_DICTIONARY_NAME}` {ON_CLUSTER_CLAUSE(on_cluster)}".strip()
    )


def DROP_DMAT_SLOT_ASSIGNMENTS_TABLE_SQL(on_cluster: bool = False) -> str:
    return f"DROP TABLE IF EXISTS `{DMAT_SLOT_ASSIGNMENTS_TABLE_NAME}` {ON_CLUSTER_CLAUSE(on_cluster)}".strip()


def INSERT_DMAT_SLOT_ASSIGNMENTS_SQL() -> str:
    # The activity supplies (team_id, column_index, property_name, generation) tuples — one
    # full snapshot under a single new generation.
    return (
        f"INSERT INTO `{DMAT_SLOT_ASSIGNMENTS_TABLE_NAME}` "
        "(team_id, column_index, property_name, generation) VALUES"
    )


def SYNC_REPLICA_DMAT_SLOT_ASSIGNMENTS_SQL() -> str:
    # STRICT waits until the replica's queue is fully drained (not just "best effort"), so
    # after this returns the node provably holds the new generation. The data cluster nodes
    # run this before the backfill mutation and before the dictionaries reload, and it's also
    # the barrier that lets the remote ingestion dictionary read a complete snapshot from any
    # data node. Fast — the table is tiny.
    return f"SYSTEM SYNC REPLICA `{DMAT_SLOT_ASSIGNMENTS_TABLE_NAME}` STRICT"


def RELOAD_DMAT_SLOT_ASSIGNMENTS_DICTIONARY_SQL() -> str:
    return f"SYSTEM RELOAD DICTIONARY `{DMAT_SLOT_ASSIGNMENTS_DICTIONARY_NAME}`"


def DELETE_OLD_DMAT_GENERATIONS_SQL(keep_generation: int) -> str:
    # Prune snapshots older than the one we just published, after the dictionaries have
    # reloaded onto it. Lightweight delete on a tiny table.
    return (
        f"DELETE FROM `{DMAT_SLOT_ASSIGNMENTS_TABLE_NAME}` WHERE generation < {int(keep_generation)}"
    )
