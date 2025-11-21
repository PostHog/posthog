from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.person.sql import KAFKA_PERSONS_TABLE_SQL, PERSONS_TABLE, PERSONS_TABLE_MV_SQL
from posthog.settings import CLICKHOUSE_CLUSTER

operations = [
    run_sql_with_exceptions(f"DROP TABLE person_mv ON CLUSTER '{CLICKHOUSE_CLUSTER}'"),
    run_sql_with_exceptions(f"DROP TABLE kafka_person ON CLUSTER '{CLICKHOUSE_CLUSTER}'"),
    run_sql_with_exceptions(
        "ALTER TABLE person ADD COLUMN IF NOT EXISTS distinct_ids Array(VARCHAR)",
        node_roles=[NodeRole.DATA, NodeRole.COORDINATOR],
        sharded=False,
        is_alter_on_replicated_table=True,
    ),
    run_sql_with_exceptions(KAFKA_PERSONS_TABLE_SQL()),
    run_sql_with_exceptions(PERSONS_TABLE_MV_SQL(target_table=PERSONS_TABLE)),
]
