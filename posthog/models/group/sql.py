from posthog.clickhouse.base_sql import COPY_ROWS_BETWEEN_TEAMS_BASE_SQL
from posthog.clickhouse.cluster import ON_CLUSTER_CLAUSE
from posthog.clickhouse.kafka_engine import kafka_engine
from posthog.kafka_client.topics import KAFKA_GROUPS

GROUPS_TABLE = "groups"


TRUNCATE_GROUPS_TABLE_SQL = f"TRUNCATE TABLE IF EXISTS {GROUPS_TABLE} {ON_CLUSTER_CLAUSE()}"


# WarpStream Kafka engine tables (coexist alongside MSK tables, same target)


# { ..., "group_0": 1325 }
# To join with events join using $group_{group_type_index} column


INSERT_GROUP_SQL = """
INSERT INTO groups (group_type_index, group_key, team_id, group_properties, created_at, _timestamp, _offset) SELECT %(group_type_index)s, %(group_key)s, %(team_id)s, %(group_properties)s, %(created_at)s, %(_timestamp)s, 0
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


def KAFKA_GROUPS_TABLE_SQL(on_cluster=True):
    return GROUPS_TABLE_BASE_SQL.format(
        table_name="kafka_" + GROUPS_TABLE,
        on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster),
        engine=kafka_engine(KAFKA_GROUPS),
        extra_fields="",
    )
