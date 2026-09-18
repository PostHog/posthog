from django.conf import settings

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.metrics.metrics2 import KAFKA_METRICS_AVRO2_MV_SELECT

DB = settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE

# `original_expiry_timestamp` counted retention from `observed_timestamp`. It now counts from
# the sample's `timestamp`. Rows already written keep their old expiry.
operations = [
    run_sql_with_exceptions(
        f"ALTER TABLE {DB}.kafka_metrics_avro2_mv MODIFY QUERY\n{KAFKA_METRICS_AVRO2_MV_SELECT()}",
        node_roles=[NodeRole.LOGS],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
]
