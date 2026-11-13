from django.conf import settings

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.logs import KAFKA_LOGS34_AVRO_MV
from posthog.run_mode import run_mode

DB = settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE

# `signature_status` is for marking a log row whose batch carried a valid signature made with the
# team's logs signing secret. The Kafka MV copies the `signature-status` Kafka header into the column,
# the same way as `internal_source` in 0361. No code sets that header yet. The logs consumers must
# remove any incoming copy of it before they set it, as they do for `internal-source`, because they
# copy other input headers to their output.
#
# The rollups do not get the column, so the volume and pattern views cannot filter on it.
#
# Every table the Kafka MV writes through gets the column before the MV selects it, so no insert can
# fail with a missing target column. The MV is dropped and recreated where 0359 runs the ingest. While
# the MV is absent the Kafka table does not consume, so the consumer group resumes from its committed
# offset.
_logs_ingest_role = NodeRole.APM if run_mode().is_deployed_cloud else NodeRole.INGESTION_EVENTS

operations = [
    run_sql_with_exceptions(
        f"ALTER TABLE {DB}.logs34 ADD COLUMN IF NOT EXISTS signature_status LowCardinality(String) DEFAULT ''",
        node_roles=[NodeRole.LOGS],
        sharded=False,
        is_alter_on_replicated_table=True,
    ),
    run_sql_with_exceptions(
        f"ALTER TABLE {DB}.logs_distributed ADD COLUMN IF NOT EXISTS signature_status LowCardinality(String) DEFAULT ''",
        node_roles=[NodeRole.LOGS],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
    run_sql_with_exceptions(
        f"ALTER TABLE {DB}.writable_logs34 ADD COLUMN IF NOT EXISTS signature_status LowCardinality(String) DEFAULT ''",
        node_roles=[_logs_ingest_role],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
    run_sql_with_exceptions(f"DROP TABLE IF EXISTS {DB}.kafka_logs34_avro_mv", node_roles=[_logs_ingest_role]),
    run_sql_with_exceptions(KAFKA_LOGS34_AVRO_MV(to_table="writable_logs34"), node_roles=[_logs_ingest_role]),
]
