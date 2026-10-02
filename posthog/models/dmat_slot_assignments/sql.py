"""Queries that refresh the dmat slot-assignments dictionary.

The weekly dmat backfill workflow writes the current `(team_id, column_index) →
property_name` mapping into `dmat_slot_assignments` and then reloads the
`dmat_slot_assignments_dict` dictionary on every host. The mutation that
follows reads the mapping via `dictGetString` / `dictHas`, which keeps the
mutation SQL constant-size regardless of how many teams have adopted dmat.

Pattern mirrors `posthog/models/web_preaggregated/team_selection.py` —
ReplacingMergeTree backing table + CLICKHOUSE-source dictionary. Differs
from that pattern in one place: we use TRUNCATE+INSERT every
cycle rather than append-only, because dmat slots can be deleted or reset
and append-only would leave stale rows in the dict that silently overwrite
columns no longer assigned to that (team, slot_index).
"""

DMAT_SLOT_ASSIGNMENTS_TABLE_NAME = "dmat_slot_assignments"
DMAT_SLOT_ASSIGNMENTS_DICTIONARY_NAME = "dmat_slot_assignments_dict"


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
