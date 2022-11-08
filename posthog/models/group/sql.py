from posthog.clickhouse.base_sql import COPY_ROWS_BETWEEN_TEAMS_BASE_SQL
from posthog.clickhouse.kafka_engine import KAFKA_COLUMNS, KAFKA_ENGINE_DEFAULT_SETTINGS, STORAGE_POLICY, kafka_engine
from posthog.clickhouse.table_engines import MergeTreeEngine, ReplacingMergeTree, ReplicationScheme
from posthog.kafka_client.topics import KAFKA_GROUPS
from posthog.models.kafka_engine_dlq.sql import KAFKA_ENGINE_DLQ_BASE_SQL, KAFKA_ENGINE_DLQ_MV_BASE_SQL
from posthog.models.person.sql import GET_ACTOR_PROPERTY_SAMPLE_JSON_VALUES
from posthog.settings import CLICKHOUSE_CLUSTER, CLICKHOUSE_DATABASE

GROUPS_TABLE = "groups"

DROP_GROUPS_TABLE_SQL = f"DROP TABLE {GROUPS_TABLE} ON CLUSTER '{CLICKHOUSE_CLUSTER}'"
TRUNCATE_GROUPS_TABLE_SQL = f"TRUNCATE TABLE {GROUPS_TABLE} ON CLUSTER '{CLICKHOUSE_CLUSTER}'"

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
{settings}
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
    settings="",
)

KAFKA_GROUPS_TABLE_SQL = lambda: GROUPS_TABLE_BASE_SQL.format(
    table_name="kafka_" + GROUPS_TABLE,
    cluster=CLICKHOUSE_CLUSTER,
    engine=kafka_engine(KAFKA_GROUPS),
    extra_fields="",
    settings=KAFKA_ENGINE_DEFAULT_SETTINGS,
)


KAFKA_GROUPS_DLQ_SQL = lambda: KAFKA_ENGINE_DLQ_BASE_SQL.format(
    table="kafka_dlq_groups",
    cluster=CLICKHOUSE_CLUSTER,
    engine=MergeTreeEngine("kafka_dlq_groups", replication_scheme=ReplicationScheme.REPLICATED),
)

KAFKA_GROUPS_DLQ_MV_SQL = lambda: KAFKA_ENGINE_DLQ_MV_BASE_SQL.format(
    view_name="kafka_dlq_groups_mv",
    target_table=f"{CLICKHOUSE_DATABASE}.kafka_dlq_groups",
    kafka_table_name=f"{CLICKHOUSE_DATABASE}.kafka_groups",
    cluster=CLICKHOUSE_CLUSTER,
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
WHERE length(_error) = 0
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

GET_GROUP_PROPERTY_SAMPLE_JSON_VALUES = GET_ACTOR_PROPERTY_SAMPLE_JSON_VALUES.format(
    table_name=GROUPS_TABLE, properties_column="group_properties"
)
