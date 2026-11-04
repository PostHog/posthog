from django.conf import settings

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.logs import KAFKA_LOGS34_AVRO_MV_SELECT
from posthog.run_mode import run_mode

DB = settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE

# MODIFY QUERY swaps the select in place, so the Kafka table keeps consuming. Rows written before
# this migration keep their attributes as they are. The roles match 0361, which last rebuilt this view.
_logs_ingest_role = NodeRole.APM if run_mode().is_deployed_cloud else NodeRole.INGESTION_EVENTS

operations = [
    run_sql_with_exceptions(
        f"ALTER TABLE {DB}.kafka_logs34_avro_mv MODIFY QUERY\n{KAFKA_LOGS34_AVRO_MV_SELECT()}",
        node_roles=[_logs_ingest_role],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
]
