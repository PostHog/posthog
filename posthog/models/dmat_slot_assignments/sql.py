"""ClickHouse schema for the dmat slot-assignments dictionary.

The weekly dmat backfill workflow writes the current `(team_id, column_index) →
property_name` mapping into `dmat_slot_assignments` and then reloads the
`dmat_slot_assignments_dict` dictionary on every host. The mutation that
follows reads the mapping via `dictGetString` / `dictHas`, which keeps the
mutation SQL constant-size regardless of how many teams have adopted dmat.

Pattern mirrors `posthog/models/web_preaggregated/team_selection.py` —
ReplacingMergeTree backing table + CLICKHOUSE-source dictionary, both ON
CLUSTER. Differs from that pattern in one place: we use TRUNCATE+INSERT every
cycle rather than append-only, because dmat slots can be deleted/reset/
compacted and append-only would leave stale rows in the dict that silently
overwrite columns no longer assigned to that (team, slot_index).
"""

from posthog.clickhouse.cluster import ON_CLUSTER_CLAUSE
from posthog.clickhouse.table_engines import ReplacingMergeTree, ReplicationScheme
from posthog.settings.data_stores import CLICKHOUSE_DATABASE, CLICKHOUSE_PASSWORD, CLICKHOUSE_USER

DMAT_SLOT_ASSIGNMENTS_TABLE_NAME = "dmat_slot_assignments"
DMAT_SLOT_ASSIGNMENTS_DICTIONARY_NAME = "dmat_slot_assignments_dict"


def DMAT_SLOT_ASSIGNMENTS_TABLE_SQL(on_cluster: bool = True) -> str:
    # NOT_SHARDED → plain `ReplacingMergeTree` (no ZK), so each host gets a truly local
    # copy of the table when created ON CLUSTER. This is what makes the per-host
    # populate-and-reload pattern in `populate_slot_assignments` correct: TRUNCATE+INSERT
    # on host A does not replicate to hosts B/C/D, so concurrent populates on multiple
    # hosts don't race through ZK and there's no insert-deduplication-across-truncate
    # window to worry about. The engine's default REPLICATED scheme would set up a
    # cluster-wide single logical table via ZK and break that mental model.
    return """
CREATE TABLE IF NOT EXISTS {table_name} {on_cluster_clause} (
    team_id UInt64,
    column_index UInt8,
    property_name String,
    version UInt32 DEFAULT toUnixTimestamp(now())
) ENGINE = {engine}
ORDER BY (team_id, column_index);
""".format(
        on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster),
        table_name=f"`{DMAT_SLOT_ASSIGNMENTS_TABLE_NAME}`",
        engine=ReplacingMergeTree(
            DMAT_SLOT_ASSIGNMENTS_TABLE_NAME,
            replication_scheme=ReplicationScheme.NOT_SHARDED,
            ver="version",
        ),
    )


def DMAT_SLOT_ASSIGNMENTS_DICTIONARY_QUERY() -> str:
    # FINAL collapses ReplacingMergeTree versions; the populate activity uses
    # TRUNCATE+INSERT so there is normally only one version per (team_id,
    # column_index) per cycle, but FINAL is still required during the brief
    # window where merges have not yet caught up to a fresh insert.
    return f"""
SELECT
    team_id,
    column_index,
    property_name
FROM
    `{CLICKHOUSE_DATABASE}`.`{DMAT_SLOT_ASSIGNMENTS_TABLE_NAME}`
FINAL
""".replace("\n", " ").strip()


def DMAT_SLOT_ASSIGNMENTS_DICTIONARY_SQL(on_cluster: bool = True) -> str:
    return """
CREATE DICTIONARY IF NOT EXISTS {dictionary_name} {on_cluster_clause} (
    team_id UInt64,
    column_index UInt8,
    property_name String
)
PRIMARY KEY team_id, column_index
SOURCE(CLICKHOUSE(QUERY '{query}' USER '{clickhouse_user}' PASSWORD '{clickhouse_password}'))
LIFETIME(MIN 600 MAX 1200)
LAYOUT(COMPLEX_KEY_HASHED())""".format(
        dictionary_name=f"`{DMAT_SLOT_ASSIGNMENTS_DICTIONARY_NAME}`",
        on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster),
        query=DMAT_SLOT_ASSIGNMENTS_DICTIONARY_QUERY(),
        clickhouse_user=CLICKHOUSE_USER,
        clickhouse_password=CLICKHOUSE_PASSWORD,
    )


def DROP_DMAT_SLOT_ASSIGNMENTS_DICTIONARY_SQL(on_cluster: bool = True) -> str:
    return (
        f"DROP DICTIONARY IF EXISTS `{DMAT_SLOT_ASSIGNMENTS_DICTIONARY_NAME}` {ON_CLUSTER_CLAUSE(on_cluster)}".strip()
    )


def DROP_DMAT_SLOT_ASSIGNMENTS_TABLE_SQL(on_cluster: bool = True) -> str:
    return f"DROP TABLE IF EXISTS `{DMAT_SLOT_ASSIGNMENTS_TABLE_NAME}` {ON_CLUSTER_CLAUSE(on_cluster)}".strip()


def TRUNCATE_DMAT_SLOT_ASSIGNMENTS_SQL() -> str:
    # No ON CLUSTER — the populate activity calls TRUNCATE on every host via
    # `cluster.map_all_hosts(...)`, which gives each host a deterministic local
    # truncation. Adding ON CLUSTER would have every host issue a cluster-wide
    # TRUNCATE, multiplying ZK chatter for no benefit.
    return f"TRUNCATE TABLE `{DMAT_SLOT_ASSIGNMENTS_TABLE_NAME}`"


def INSERT_DMAT_SLOT_ASSIGNMENTS_SQL() -> str:
    return f"INSERT INTO `{DMAT_SLOT_ASSIGNMENTS_TABLE_NAME}` (team_id, column_index, property_name) VALUES"


def RELOAD_DMAT_SLOT_ASSIGNMENTS_DICTIONARY_SQL() -> str:
    return f"SYSTEM RELOAD DICTIONARY `{DMAT_SLOT_ASSIGNMENTS_DICTIONARY_NAME}`"
