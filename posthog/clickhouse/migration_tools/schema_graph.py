"""Table ecosystem graph — models cross-cluster relationships. Used by reconcile and validator."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RemoteTableRef:
    """A distributed table on one cluster that reads from another cluster."""

    table_name: str
    source_cluster: str
    target_cluster: str
    source_table: str


@dataclass
class DictRef:
    """A dictionary that reads from a table (typically a distributed table)."""

    dict_name: str
    source_table: str


@dataclass
class TableEcosystem:
    """All objects (sharded, distributed, MV, Kafka, dict) that must stay in sync for one data pipeline."""

    base_name: str

    # Core tables
    sharded_table: str
    distributed_writable: str | None = None
    distributed_readable: str | None = None

    # Ingestion path
    kafka_table: str | None = None
    materialized_view: str | None = None

    # Cross-cluster dependencies
    remote_tables: list[RemoteTableRef] = field(default_factory=list)
    dictionaries: list[DictRef] = field(default_factory=list)

    def all_tables(self) -> set[str]:
        """Return every table/object name in this ecosystem."""
        names = {self.sharded_table}
        if self.distributed_writable:
            names.add(self.distributed_writable)
        if self.distributed_readable:
            names.add(self.distributed_readable)
        if self.kafka_table:
            names.add(self.kafka_table)
        if self.materialized_view:
            names.add(self.materialized_view)
        for ref in self.remote_tables:
            names.add(ref.table_name)
        for d in self.dictionaries:
            names.add(d.dict_name)
        return names


EVENTS_ECOSYSTEM = TableEcosystem(
    base_name="events",
    sharded_table="sharded_events",
    distributed_writable="writable_events",
    distributed_readable="events",
    kafka_table="kafka_events_json",
    materialized_view="events_json_mv",
)

EVENTS_RECENT_ECOSYSTEM = TableEcosystem(
    base_name="events_recent",
    sharded_table="sharded_events_recent",
    distributed_writable="writable_events_recent",
    distributed_readable="events_recent",
    kafka_table="kafka_events_recent_json",
    materialized_view="events_recent_json_mv",
)

SESSIONS_V3_ECOSYSTEM = TableEcosystem(
    base_name="sessions_v3",
    sharded_table="sharded_raw_sessions_v3",
    distributed_writable="writable_raw_sessions_v3",
    distributed_readable="raw_sessions_v3",
    kafka_table=None,
    materialized_view="raw_sessions_v3_mv",
    remote_tables=[
        RemoteTableRef(
            table_name="channel_definition",
            source_cluster="main",
            target_cluster="sessions",
            source_table="channel_definition",
        ),
        RemoteTableRef(
            table_name="web_pre_aggregated_teams",
            source_cluster="main",
            target_cluster="sessions",
            source_table="web_pre_aggregated_teams",
        ),
    ],
    dictionaries=[
        DictRef(dict_name="channel_definition_dict", source_table="channel_definition"),
        DictRef(dict_name="web_pre_aggregated_teams_dict", source_table="web_pre_aggregated_teams"),
    ],
)

PERSON_ECOSYSTEM = TableEcosystem(
    base_name="person",
    sharded_table="person",
    distributed_writable="writable_person",
    distributed_readable=None,  # reads go directly to the local person table
    kafka_table="kafka_person",
    materialized_view="person_mv",
)

SESSION_REPLAY_EVENTS_ECOSYSTEM = TableEcosystem(
    base_name="session_replay_events",
    sharded_table="sharded_session_replay_events",
    distributed_writable="writable_session_replay_events",
    distributed_readable="session_replay_events",
    kafka_table="kafka_session_replay_events",
    materialized_view="session_replay_events_mv",
)

# Registry: maps any table name -> its ecosystem
KNOWN_ECOSYSTEMS: list[TableEcosystem] = [
    EVENTS_ECOSYSTEM,
    EVENTS_RECENT_ECOSYSTEM,
    SESSIONS_V3_ECOSYSTEM,
    PERSON_ECOSYSTEM,
    SESSION_REPLAY_EVENTS_ECOSYSTEM,
]

# Reverse lookup: table_name -> TableEcosystem
_TABLE_TO_ECOSYSTEM: dict[str, TableEcosystem] = {}
for _eco in KNOWN_ECOSYSTEMS:
    for _tbl in _eco.all_tables():
        _TABLE_TO_ECOSYSTEM[_tbl] = _eco


def lookup_ecosystem(table_name: str) -> TableEcosystem | None:
    """Find the ecosystem a table belongs to, or None."""
    return _TABLE_TO_ECOSYSTEM.get(table_name)


def get_ecosystem_by_name(name: str) -> TableEcosystem | None:
    """Find an ecosystem by its base_name."""
    for eco in KNOWN_ECOSYSTEMS:
        if eco.base_name == name:
            return eco
    return None
