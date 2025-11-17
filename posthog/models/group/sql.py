from posthog import settings
from posthog.clickhouse.base_sql import COPY_ROWS_BETWEEN_TEAMS_BASE_SQL
from posthog.clickhouse.cluster import ON_CLUSTER_CLAUSE
from posthog.clickhouse.kafka_engine import KAFKA_COLUMNS, STORAGE_POLICY, kafka_engine
from posthog.clickhouse.table_engines import Distributed, ReplacingMergeTree
from posthog.kafka_client.topics import KAFKA_GROUPS
from posthog.settings import CLICKHOUSE_CLUSTER

GROUPS_TABLE = "groups"
GROUPS_TABLE_MV = f"{GROUPS_TABLE}_mv"
GROUPS_WRITABLE_TABLE = f"writable_{GROUPS_TABLE}"
KAFKA_GROUPS_TABLE = f"kafka_{GROUPS_TABLE}"

DROP_GROUPS_TABLE_SQL = f"DROP TABLE {GROUPS_TABLE} ON CLUSTER '{CLICKHOUSE_CLUSTER}'"
DROP_GROUPS_TABLE_MV_SQL = f"DROP TABLE IF EXISTS {GROUPS_TABLE_MV}"
DROP_KAFKA_GROUPS_TABLE_SQL = f"DROP TABLE IF EXISTS {KAFKA_GROUPS_TABLE}"

TRUNCATE_GROUPS_TABLE_SQL = f"TRUNCATE TABLE IF EXISTS {GROUPS_TABLE} ON CLUSTER '{CLICKHOUSE_CLUSTER}'"

GROUPS_TABLE_BASE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name} {on_cluster_clause}
(
    group_type_index UInt8,
    group_key VARCHAR,
    created_at DateTime64,
    team_id Int64,
    group_properties VARCHAR
    {extra_fields}
) ENGINE = {engine}
"""


def GROUPS_TABLE_ENGINE():
    return ReplacingMergeTree(GROUPS_TABLE, ver="_timestamp")


def GROUPS_TABLE_SQL(on_cluster=True):
    return (
        GROUPS_TABLE_BASE_SQL
        + """ORDER BY (team_id, group_type_index, group_key)
{storage_policy}
"""
    ).format(
        table_name=GROUPS_TABLE,
        on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster),
        engine=GROUPS_TABLE_ENGINE(),
        extra_fields=KAFKA_COLUMNS,
        storage_policy=STORAGE_POLICY(),
    )


def KAFKA_GROUPS_TABLE_SQL(on_cluster=True):
    return GROUPS_TABLE_BASE_SQL.format(
        table_name="kafka_" + GROUPS_TABLE,
        on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster),
        engine=kafka_engine(KAFKA_GROUPS),
        extra_fields="",
    )


def GROUPS_WRITABLE_TABLE_SQL():
    # This is a table used for writing from the ingestion layer. It's not sharded, thus it uses the single shard cluster.
    return GROUPS_TABLE_BASE_SQL.format(
        table_name="writable_" + GROUPS_TABLE,
        on_cluster_clause=ON_CLUSTER_CLAUSE(False),
        engine=Distributed(data_table=GROUPS_TABLE, cluster=settings.CLICKHOUSE_SINGLE_SHARD_CLUSTER),
        extra_fields=KAFKA_COLUMNS,
    )


def GROUPS_TABLE_MV_SQL(target_table=GROUPS_WRITABLE_TABLE, on_cluster=True):
    return f"""
CREATE MATERIALIZED VIEW IF NOT EXISTS {GROUPS_TABLE_MV} {ON_CLUSTER_CLAUSE(on_cluster)}
TO {target_table}
AS SELECT
group_type_index,
group_key,
created_at,
team_id,
group_properties,
_timestamp,
_offset
FROM {KAFKA_GROUPS_TABLE}
"""


# { ..., "group_0": 1325 }
# To join with events join using $group_{group_type_index} column


INSERT_GROUP_SQL = """
INSERT INTO groups (group_type_index, group_key, team_id, group_properties, created_at, _timestamp, _offset) SELECT %(group_type_index)s, %(group_key)s, %(team_id)s, %(group_properties)s, %(created_at)s, %(_timestamp)s, 0
"""

GET_GROUP_IDS_BY_PROPERTY_SQL = """
SELECT DISTINCT group_key
FROM groups
WHERE team_id = %(team_id)s AND group_type_index = %({group_type_index_var})s {filters}
"""

#
# Demo data
#

COPY_GROUPS_BETWEEN_TEAMS = COPY_ROWS_BETWEEN_TEAMS_BASE_SQL.format(
    table_name=GROUPS_TABLE,
    columns_except_team_id="""group_type_index, group_key, group_properties, created_at, _timestamp, _offset""",
)

SELECT_GROUPS_OF_TEAM = """SELECT * FROM {table_name} WHERE team_id = %(source_team_id)s""".format(
    table_name=GROUPS_TABLE
)
