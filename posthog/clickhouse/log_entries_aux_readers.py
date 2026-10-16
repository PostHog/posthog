from django.conf import settings

from posthog.clickhouse.cluster import ON_CLUSTER_CLAUSE
from posthog.clickhouse.kafka_engine import KAFKA_COLUMNS
from posthog.clickhouse.property_groups import property_groups
from posthog.clickhouse.table_engines import Distributed
from posthog.heatmaps.sql import DISTRIBUTED_HEATMAPS_TABLE_SQL
from posthog.models.event.sql import (
    EVENTS_DATA_TABLE,
    EVENTS_TABLE_BASE_SQL,
    EVENTS_TABLE_DYNAMICALLY_MATERIALIZED_COLUMNS,
    EVENTS_TABLE_PROXY_MATERIALIZED_COLUMNS,
    INSERTED_AT_COLUMN,
    KAFKA_CONSUMER_BREADCRUMBS_COLUMN,
)
from posthog.models.group.sql import GROUPS_TABLE, GROUPS_TABLE_BASE_SQL
from posthog.models.person.sql import (
    PERSON_DISTINCT_ID2_TABLE,
    PERSON_DISTINCT_ID2_TABLE_BASE_SQL,
    PERSON_DISTINCT_ID_OVERRIDES_TABLE,
    PERSON_DISTINCT_ID_OVERRIDES_TABLE_BASE_SQL,
    PERSON_STATIC_COHORT_BASE_SQL,
    PERSON_STATIC_COHORT_TABLE,
    PERSONS_TABLE,
    PERSONS_TABLE_BASE_SQL,
)
from posthog.models.raw_sessions.sessions_v2 import (
    DISTRIBUTED_RAW_SESSIONS_TABLE_SQL,
    RAW_SESSIONS_TABLE_BASE_SQL,
    TABLE_BASE_NAME as RAW_SESSIONS_TABLE,
)
from posthog.run_mode import run_mode
from posthog.session_recordings.sql.session_replay_event_sql import DISTRIBUTED_SESSION_REPLAY_EVENTS_TABLE_SQL

# Read-only Distributed readers on the aux cluster for the tables that log_entries queries join.
# `log_entries` is a Distributed table over the aux cluster, so ClickHouse runs a JOIN against it on
# the aux nodes, and the right-hand table must resolve there. Each reader forwards to the cluster that
# stores the table. Column lists come from the source templates; the env-specific mat_ columns on the
# cloud data clusters are not declared here (posthog-cloud-infra owns them).

_SINGLE_SHARD_READ_KEY = "rand()"


def _single_shard_reader(table_name: str) -> Distributed:
    # The non-sharded replicated tables hold a full copy on every main node, so read one replica.
    return Distributed(
        data_table=table_name, cluster=settings.CLICKHOUSE_SINGLE_SHARD_CLUSTER, sharding_key=_SINGLE_SHARD_READ_KEY
    )


def AUX_PERSON_READER_SQL() -> str:
    return PERSONS_TABLE_BASE_SQL.format(
        table_name=PERSONS_TABLE,
        on_cluster_clause=ON_CLUSTER_CLAUSE(False),
        engine=_single_shard_reader(PERSONS_TABLE),
        extra_fields=KAFKA_COLUMNS,
    )


def AUX_PERSON_DISTINCT_ID2_READER_SQL() -> str:
    return PERSON_DISTINCT_ID2_TABLE_BASE_SQL.format(
        table_name=PERSON_DISTINCT_ID2_TABLE,
        on_cluster_clause=ON_CLUSTER_CLAUSE(False),
        engine=_single_shard_reader(PERSON_DISTINCT_ID2_TABLE),
        extra_fields=f"{KAFKA_COLUMNS}, _partition UInt64",
    )


def AUX_PERSON_DISTINCT_ID_OVERRIDES_READER_SQL() -> str:
    return PERSON_DISTINCT_ID_OVERRIDES_TABLE_BASE_SQL.format(
        table_name=PERSON_DISTINCT_ID_OVERRIDES_TABLE,
        on_cluster_clause=ON_CLUSTER_CLAUSE(False),
        engine=_single_shard_reader(PERSON_DISTINCT_ID_OVERRIDES_TABLE),
        extra_fields=f"{KAFKA_COLUMNS}, _partition UInt64",
    )


def AUX_PERSON_STATIC_COHORT_READER_SQL() -> str:
    return PERSON_STATIC_COHORT_BASE_SQL.format(
        table_name=PERSON_STATIC_COHORT_TABLE,
        on_cluster_clause=ON_CLUSTER_CLAUSE(False),
        engine=_single_shard_reader(PERSON_STATIC_COHORT_TABLE),
        extra_fields=KAFKA_COLUMNS,
    )


def AUX_GROUPS_READER_SQL() -> str:
    return GROUPS_TABLE_BASE_SQL.format(
        table_name=GROUPS_TABLE,
        on_cluster_clause=ON_CLUSTER_CLAUSE(False),
        engine=_single_shard_reader(GROUPS_TABLE),
        # is_deleted arrived by ALTER (migration 0112), so the base template does not carry it.
        extra_fields=f"{KAFKA_COLUMNS}, is_deleted Bool",
    )


def AUX_COHORTPEOPLE_READER_SQL() -> str:
    return f"""
CREATE TABLE IF NOT EXISTS cohortpeople
(
    person_id UUID,
    cohort_id Int64,
    team_id Int64,
    sign Int8,
    version UInt64
) ENGINE = {_single_shard_reader("cohortpeople")}
"""


def AUX_CHANNEL_DEFINITION_READER_SQL() -> str:
    return f"""
CREATE TABLE IF NOT EXISTS channel_definition
(
    domain String NOT NULL,
    kind String NOT NULL,
    domain_type String NULL,
    type_if_paid String NULL,
    type_if_organic String NULL
) ENGINE = {_single_shard_reader("channel_definition")}
"""


def AUX_RAW_SESSIONS_READER_SQL() -> str:
    # Cloud stores raw_sessions on the sessions satellite. Local stacks keep it on the data cluster
    # behind the usual Distributed table, so the reader matches that one there.
    if not run_mode().is_deployed_cloud:
        return DISTRIBUTED_RAW_SESSIONS_TABLE_SQL(on_cluster=False)
    return RAW_SESSIONS_TABLE_BASE_SQL.format(
        table_name=RAW_SESSIONS_TABLE,
        on_cluster_clause=ON_CLUSTER_CLAUSE(False),
        # The sessions satellite has no settings entry; the name is the same in every cloud env.
        engine=Distributed(data_table=RAW_SESSIONS_TABLE, cluster="sessions", sharding_key="cityHash64(session_id_v7)"),
    )


# Migration 0198 dropped this property group from every events table, but the group stays defined
# (hidden) for migration 0197, so the shared template still emits its column.
_RETIRED_EVENTS_PROPERTY_GROUP_COLUMN = "properties_group_ai_large"


def AUX_EVENTS_READER_SQL() -> str:
    # The main cluster's events proxy, minus the retired group, so the reader matches its remote table.
    group_pieces = list(property_groups.get_create_table_pieces("events"))
    all_groups = ", ".join(group_pieces)
    live_groups = ", ".join(piece for piece in group_pieces if _RETIRED_EVENTS_PROPERTY_GROUP_COLUMN not in piece)
    assert all_groups in EVENTS_TABLE_PROXY_MATERIALIZED_COLUMNS
    return EVENTS_TABLE_BASE_SQL.format(
        table_name="events",
        on_cluster_clause=ON_CLUSTER_CLAUSE(False),
        engine=Distributed(data_table=EVENTS_DATA_TABLE(), sharding_key="sipHash64(distinct_id)"),
        extra_fields=KAFKA_COLUMNS + INSERTED_AT_COLUMN + KAFKA_CONSUMER_BREADCRUMBS_COLUMN,
        dynamically_materialized_columns=EVENTS_TABLE_DYNAMICALLY_MATERIALIZED_COLUMNS(),
        materialized_columns=EVENTS_TABLE_PROXY_MATERIALIZED_COLUMNS.replace(all_groups, live_groups),
        indexes="",
    )


def LOG_ENTRIES_AUX_JOIN_READERS_SQL() -> list[str]:
    return [
        AUX_EVENTS_READER_SQL(),
        DISTRIBUTED_HEATMAPS_TABLE_SQL(),
        DISTRIBUTED_SESSION_REPLAY_EVENTS_TABLE_SQL(on_cluster=False),
        AUX_PERSON_READER_SQL(),
        AUX_PERSON_DISTINCT_ID2_READER_SQL(),
        AUX_PERSON_DISTINCT_ID_OVERRIDES_READER_SQL(),
        AUX_PERSON_STATIC_COHORT_READER_SQL(),
        AUX_GROUPS_READER_SQL(),
        AUX_COHORTPEOPLE_READER_SQL(),
        AUX_CHANNEL_DEFINITION_READER_SQL(),
        AUX_RAW_SESSIONS_READER_SQL(),
    ]
