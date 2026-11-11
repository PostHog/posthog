from django.conf import settings

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.logs import (
    KAFKA_LOGS34_AVRO_MV,
    LOGS34_TO_PATTERN_BUCKETS_MV_SELECT,
    LOGS34_TO_VOLUME_BUCKETS_MV_SELECT,
)
from posthog.run_mode import run_mode

DB = settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE

# `internal_source` marks a log row that PostHog wrote about a team's own use of PostHog. The
# ingestion consumer sets the `internal-source` Kafka header only after it verifies the batch
# signature, and the Kafka MV copies the header into the column. A message without the header gets
# '', because indexOf returns 0 and array index 0 returns the element type's default value.
#
# Every storage and Distributed table gets the column before an MV selects it, so no insert can fail
# with a missing target column.
#
# The rollups carry the column as a grouping dimension. ClickHouse allows a new column at the end of
# the sort key in the same ALTER that adds it, so the change is metadata only and existing parts read
# the column as ''. That append is forbidden for a column with a DEFAULT expression, so the rollup
# columns rely on the String type default instead. The rollup MVs change by MODIFY QUERY, which
# swaps the query in place, so no insert into logs34 lands while a rollup MV is missing.
#
# The Kafka MV is dropped and recreated where 0359 runs the ingest: the apm nodes in the cloud envs,
# the ingestion-events node in the multinode stack, in both cases writing through `writable_logs34`.
# While the MV is absent the Kafka table does not consume, so the consumer group resumes from its
# committed offset.
_logs_ingest_role = NodeRole.APM if run_mode().is_deployed_cloud else NodeRole.INGESTION_EVENTS

operations = [
    run_sql_with_exceptions(
        f"ALTER TABLE {DB}.logs34 ADD COLUMN IF NOT EXISTS internal_source LowCardinality(String) DEFAULT ''",
        node_roles=[NodeRole.LOGS],
        sharded=False,
        is_alter_on_replicated_table=True,
    ),
    run_sql_with_exceptions(
        f"ALTER TABLE {DB}.logs_distributed ADD COLUMN IF NOT EXISTS internal_source LowCardinality(String) DEFAULT ''",
        node_roles=[NodeRole.LOGS],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
    run_sql_with_exceptions(
        f"ALTER TABLE {DB}.logs_volume_buckets "
        "ADD COLUMN IF NOT EXISTS internal_source LowCardinality(String) AFTER severity_text, "
        "MODIFY ORDER BY (team_id, time_bucket, service_name, namespace, environment, severity_text, internal_source)",
        node_roles=[NodeRole.LOGS],
        sharded=False,
        is_alter_on_replicated_table=True,
    ),
    run_sql_with_exceptions(
        f"ALTER TABLE {DB}.logs_volume_buckets_distributed "
        "ADD COLUMN IF NOT EXISTS internal_source LowCardinality(String) AFTER severity_text",
        node_roles=[NodeRole.LOGS],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
    run_sql_with_exceptions(
        f"ALTER TABLE {DB}.logs_pattern_buckets "
        "ADD COLUMN IF NOT EXISTS internal_source LowCardinality(String) AFTER pattern, "
        "MODIFY ORDER BY (team_id, time_bucket, service_name, namespace, environment, severity_text, "
        "pattern_version, pattern, internal_source)",
        node_roles=[NodeRole.LOGS],
        sharded=False,
        is_alter_on_replicated_table=True,
    ),
    run_sql_with_exceptions(
        f"ALTER TABLE {DB}.logs_pattern_buckets_distributed "
        "ADD COLUMN IF NOT EXISTS internal_source LowCardinality(String) AFTER pattern",
        node_roles=[NodeRole.LOGS],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
    run_sql_with_exceptions(
        f"ALTER TABLE {DB}.logs34_to_volume_buckets MODIFY QUERY {LOGS34_TO_VOLUME_BUCKETS_MV_SELECT()}",
        node_roles=[NodeRole.LOGS],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
    run_sql_with_exceptions(
        f"ALTER TABLE {DB}.logs34_to_pattern_buckets MODIFY QUERY {LOGS34_TO_PATTERN_BUCKETS_MV_SELECT()}",
        node_roles=[NodeRole.LOGS],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
    run_sql_with_exceptions(
        f"ALTER TABLE {DB}.writable_logs34 ADD COLUMN IF NOT EXISTS internal_source LowCardinality(String) DEFAULT ''",
        node_roles=[_logs_ingest_role],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
    run_sql_with_exceptions(f"DROP TABLE IF EXISTS {DB}.kafka_logs34_avro_mv", node_roles=[_logs_ingest_role]),
    run_sql_with_exceptions(KAFKA_LOGS34_AVRO_MV(to_table="writable_logs34"), node_roles=[_logs_ingest_role]),
]
