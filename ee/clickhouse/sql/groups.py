from ee.kafka_client.topics import KAFKA_GROUPS
from posthog.settings import CLICKHOUSE_CLUSTER, CLICKHOUSE_DATABASE

from .clickhouse import KAFKA_COLUMNS, REPLACING_MERGE_TREE, STORAGE_POLICY, kafka_engine, table_engine

GROUPS_TABLE = "groups"

DROP_GROUPS_TABLE_SQL = f"DROP TABLE {GROUPS_TABLE} ON CLUSTER {CLICKHOUSE_CLUSTER}"

GROUPS_TABLE_BASE_SQL = """
CREATE TABLE {table_name} ON CLUSTER {cluster}
(
    group_type_index UInt8,
    group_key VARCHAR,
    created_at DateTime64,
    team_id Int64,
    group_properties VARCHAR
    {extra_fields}
) ENGINE = {engine}
"""

GROUPS_TABLE_SQL = (
    GROUPS_TABLE_BASE_SQL
    + """Order By (team_id, group_type_index, group_key)
{storage_policy}
"""
).format(
    table_name=GROUPS_TABLE,
    cluster=CLICKHOUSE_CLUSTER,
    engine=table_engine(GROUPS_TABLE, "_timestamp", REPLACING_MERGE_TREE),
    extra_fields=KAFKA_COLUMNS,
    storage_policy=STORAGE_POLICY,
)

KAFKA_GROUPS_TABLE_SQL = GROUPS_TABLE_BASE_SQL.format(
    table_name="kafka_" + GROUPS_TABLE, cluster=CLICKHOUSE_CLUSTER, engine=kafka_engine(KAFKA_GROUPS), extra_fields="",
)

# You must include the database here because of a bug in clickhouse
# related to https://github.com/ClickHouse/ClickHouse/issues/10471
GROUPS_TABLE_MV_SQL = f"""
CREATE MATERIALIZED VIEW {GROUPS_TABLE}_mv ON CLUSTER {CLICKHOUSE_CLUSTER}
TO {CLICKHOUSE_DATABASE}.{GROUPS_TABLE}
AS SELECT
group_type_index,
group_key,
created_at,
team_id,
group_properties,
_timestamp,
_offset
FROM {CLICKHOUSE_DATABASE}.kafka_{GROUPS_TABLE}
"""

# { ..., "group_0": 1325 }
# To join with events join using $group_{group_type_index} column

DROP_GROUPS_TABLE_SQL = f"DROP TABLE IF EXISTS {GROUPS_TABLE} ON CLUSTER {CLICKHOUSE_CLUSTER}"

INSERT_GROUP_SQL = """
INSERT INTO groups (group_type_index, group_key, team_id, group_properties, created_at, _timestamp, _offset) SELECT %(group_type_index)s, %(group_key)s, %(team_id)s, %(group_properties)s, %(created_at)s, %(_timestamp)s, 0
"""
