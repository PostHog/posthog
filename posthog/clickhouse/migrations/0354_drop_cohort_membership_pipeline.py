from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

# The realtime cohort pipeline writes membership to Postgres now, so this ClickHouse copy has had
# no producer since the legacy one was deleted. The Kafka table must go before the
# warpstream_calculated_events named collection it resolves is removed from the ClickHouse config:
# a Kafka table whose collection is missing fails to attach on the next server restart.
#
# Writers go first (MVs, then Kafka tables) so no insert targets a dropped table, then the
# Distributed proxy, then storage. The *_ws pair exists only on cloud (0245) and the MSK pair only
# on local/hobby (0175; cloud dropped it in 0248), hence IF EXISTS on both.
operations = [
    run_sql_with_exceptions("DROP TABLE IF EXISTS cohort_membership_ws_mv", node_roles=[NodeRole.INGESTION_MEDIUM]),
    run_sql_with_exceptions("DROP TABLE IF EXISTS kafka_cohort_membership_ws", node_roles=[NodeRole.INGESTION_MEDIUM]),
    run_sql_with_exceptions("DROP TABLE IF EXISTS cohort_membership_mv", node_roles=[NodeRole.INGESTION_MEDIUM]),
    run_sql_with_exceptions("DROP TABLE IF EXISTS kafka_cohort_membership", node_roles=[NodeRole.INGESTION_MEDIUM]),
    run_sql_with_exceptions("DROP TABLE IF EXISTS writable_cohort_membership", node_roles=[NodeRole.INGESTION_MEDIUM]),
    run_sql_with_exceptions(
        "DROP TABLE IF EXISTS cohort_membership SETTINGS max_table_size_to_drop = 0",
        node_roles=[NodeRole.DATA],
    ),
]
