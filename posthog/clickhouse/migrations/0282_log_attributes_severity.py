from django.conf import settings

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.logs import KAFKA_LOGS34_AVRO_MV, LOGS34_TO_LOG_ATTRIBUTES_MV, LOGS34_TO_RESOURCE_ATTRIBUTES_MV

_DATABASE = settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE

# log_attributes2 is an AggregatingMergeTree, so its sort key is its aggregation key: severity_text
# must be in ORDER BY or rows of differing severity merge together and the per-severity counts
# collapse. ClickHouse only lets MODIFY ORDER BY add a column that is being added in the *same* ALTER
# and has no default expression, so the ADD COLUMN and MODIFY ORDER BY are combined and the column
# carries no DEFAULT (existing rows still fill the implicit '').
ADD_SEVERITY_AND_EXTEND_ORDER_BY = f"""
ALTER TABLE {_DATABASE}.log_attributes2
ADD COLUMN IF NOT EXISTS `severity_text` LowCardinality(String),
MODIFY ORDER BY (team_id, attribute_type, time_bucket, resource_fingerprint, attribute_key, attribute_value, severity_text)
"""

ADD_SEVERITY_COLUMN_DISTRIBUTED = f"""
ALTER TABLE {_DATABASE}.log_attributes_distributed
ADD COLUMN IF NOT EXISTS `severity_text` LowCardinality(String)
"""

DROP_KAFKA_MV = f"DROP TABLE IF EXISTS {_DATABASE}.kafka_logs34_avro_mv"
DROP_LOG_ATTRIBUTES_MV = f"DROP TABLE IF EXISTS {_DATABASE}.logs34_to_log_attributes"
DROP_RESOURCE_ATTRIBUTES_MV = f"DROP TABLE IF EXISTS {_DATABASE}.logs34_to_resource_attributes"

operations = [
    run_sql_with_exceptions(
        ADD_SEVERITY_AND_EXTEND_ORDER_BY,
        node_roles=[NodeRole.LOGS],
        sharded=False,
        is_alter_on_replicated_table=True,
    ),
    run_sql_with_exceptions(
        ADD_SEVERITY_COLUMN_DISTRIBUTED,
        node_roles=[NodeRole.LOGS],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
    # Pause ingestion into logs34 by dropping the Kafka MV first, so no rows land in logs34 while the
    # attribute MVs are absent. Recreate both attribute MVs to emit severity_text, then re-add the
    # Kafka MV at the end — it resumes from the committed Kafka offset, so no data is lost.
    run_sql_with_exceptions(
        DROP_KAFKA_MV,
        node_roles=[NodeRole.LOGS],
    ),
    run_sql_with_exceptions(
        DROP_LOG_ATTRIBUTES_MV,
        node_roles=[NodeRole.LOGS],
    ),
    run_sql_with_exceptions(
        LOGS34_TO_LOG_ATTRIBUTES_MV(),
        node_roles=[NodeRole.LOGS],
    ),
    run_sql_with_exceptions(
        DROP_RESOURCE_ATTRIBUTES_MV,
        node_roles=[NodeRole.LOGS],
    ),
    run_sql_with_exceptions(
        LOGS34_TO_RESOURCE_ATTRIBUTES_MV(),
        node_roles=[NodeRole.LOGS],
    ),
    run_sql_with_exceptions(
        KAFKA_LOGS34_AVRO_MV(),
        node_roles=[NodeRole.LOGS],
    ),
]
