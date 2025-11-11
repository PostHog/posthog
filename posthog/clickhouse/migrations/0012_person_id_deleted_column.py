from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.person.sql import KAFKA_PERSONS_DISTINCT_ID_TABLE_SQL, PERSONS_DISTINCT_ID_TABLE_MV_SQL

operations = [
    run_sql_with_exceptions(f"DROP TABLE IF EXISTS person_distinct_id_mv"),
    run_sql_with_exceptions(f"DROP TABLE IF EXISTS kafka_person_distinct_id"),
    run_sql_with_exceptions(
        f"ALTER TABLE person_distinct_id ADD COLUMN IF NOT EXISTS is_deleted Int8 DEFAULT 0",
        node_roles=[NodeRole.DATA, NodeRole.COORDINATOR],
        sharded=False,
        is_alter_on_replicated_table=True,
    ),
    run_sql_with_exceptions(KAFKA_PERSONS_DISTINCT_ID_TABLE_SQL()),
    run_sql_with_exceptions(PERSONS_DISTINCT_ID_TABLE_MV_SQL()),
]
