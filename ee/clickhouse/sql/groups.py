from ee.clickhouse.sql.clickhouse import KAFKA_COLUMNS, STORAGE_POLICY, kafka_engine
from ee.clickhouse.sql.table_engines import ReplacingMergeTree
from ee.kafka_client.topics import KAFKA_GROUPS
from posthog.settings import CLICKHOUSE_CLUSTER, CLICKHOUSE_DATABASE

GROUPS_TABLE = "groups"

DROP_GROUPS_TABLE_SQL = f"DROP TABLE {GROUPS_TABLE} ON CLUSTER '{CLICKHOUSE_CLUSTER}'"

GROUPS_TABLE_BASE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name} ON CLUSTER '{cluster}'
(
    group_type_index UInt8,
    group_key VARCHAR,
    created_at DateTime64,
    team_id Int64,
    group_properties VARCHAR
    {extra_fields}
) ENGINE = {engine}
"""

GROUPS_TABLE_ENGINE = lambda: ReplacingMergeTree(GROUPS_TABLE, ver="_timestamp")
GROUPS_TABLE_SQL = lambda: (
    GROUPS_TABLE_BASE_SQL
    + """Order By (team_id, group_type_index, group_key)
{storage_policy}
"""
).format(
    table_name=GROUPS_TABLE,
    cluster=CLICKHOUSE_CLUSTER,
    engine=GROUPS_TABLE_ENGINE(),
    extra_fields=KAFKA_COLUMNS,
    storage_policy=STORAGE_POLICY(),
)

KAFKA_GROUPS_TABLE_SQL = lambda: GROUPS_TABLE_BASE_SQL.format(
    table_name="kafka_" + GROUPS_TABLE, cluster=CLICKHOUSE_CLUSTER, engine=kafka_engine(KAFKA_GROUPS), extra_fields="",
)

# You must include the database here because of a bug in clickhouse
# related to https://github.com/ClickHouse/ClickHouse/issues/10471
GROUPS_TABLE_MV_SQL = f"""
CREATE MATERIALIZED VIEW {GROUPS_TABLE}_mv ON CLUSTER '{CLICKHOUSE_CLUSTER}'
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

TRUNCATE_GROUPS_TABLE_SQL = f"TRUNCATE TABLE IF EXISTS {GROUPS_TABLE} ON CLUSTER '{CLICKHOUSE_CLUSTER}'"

INSERT_GROUP_SQL = """
INSERT INTO groups (group_type_index, group_key, team_id, group_properties, created_at, _timestamp, _offset) SELECT %(group_type_index)s, %(group_key)s, %(team_id)s, %(group_properties)s, %(created_at)s, %(_timestamp)s, 0
"""

GET_GROUP_IDS_BY_PROPERTY_SQL = """
SELECT DISTINCT group_key
FROM groups
WHERE team_id = %(team_id)s AND group_type_index = %({group_type_index_var})s {filters}
"""
