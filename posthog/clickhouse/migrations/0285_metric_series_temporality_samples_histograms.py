from django.conf import settings

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

# The events-model tables can't answer rate() or histogram-quantile questions as
# originally shipped: counters need aggregation_temporality/is_monotonic to know
# whether to diff, and histogram points collapsed to their sum with the bucket
# arrays dropped. Add both while the tables are empty (US) / freshly truncated at
# the fingerprint cutover (EU), plus the series TTL so dead series age out 90 days
# after their last sample (samples themselves expire at 30).
#
# This migration covers the storage tables only. The ingest MVs that populate the
# new columns (and carry the table-qualified NULL-fingerprint guard) are
# hand-managed, like all Avro Kafka-engine objects on the logs cluster — the
# canonical definitions live in bin/clickhouse-metrics.sql and must be dropped and
# recreated on each region as part of the fingerprint-cutover DDL. Until that
# manual step runs, rows written by the old MVs simply leave the new columns at
# their defaults.

_DB = settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE

ALTER_SERIES_BASE = f"""
ALTER TABLE {_DB}.metric_series1
    ADD COLUMN IF NOT EXISTS `aggregation_temporality` LowCardinality(String) AFTER unit,
    ADD COLUMN IF NOT EXISTS `is_monotonic` Bool DEFAULT false AFTER aggregation_temporality
"""

ALTER_SERIES_TTL = f"""
ALTER TABLE {_DB}.metric_series1
    MODIFY TTL toDateTime(last_seen) + INTERVAL 90 DAY DELETE
"""

ALTER_SAMPLES_BASE = f"""
ALTER TABLE {_DB}.metric_samples1
    ADD COLUMN IF NOT EXISTS `count` UInt64 DEFAULT 1 AFTER value,
    ADD COLUMN IF NOT EXISTS `histogram_bounds` Array(Float64) AFTER count,
    ADD COLUMN IF NOT EXISTS `histogram_counts` Array(UInt64) AFTER histogram_bounds
"""

ALTER_SERIES_DISTRIBUTED = f"""
ALTER TABLE {_DB}.metric_series
    ADD COLUMN IF NOT EXISTS `aggregation_temporality` LowCardinality(String) AFTER unit,
    ADD COLUMN IF NOT EXISTS `is_monotonic` Bool DEFAULT false AFTER aggregation_temporality
"""

ALTER_SAMPLES_DISTRIBUTED = f"""
ALTER TABLE {_DB}.metric_samples
    ADD COLUMN IF NOT EXISTS `count` UInt64 DEFAULT 1 AFTER value,
    ADD COLUMN IF NOT EXISTS `histogram_bounds` Array(Float64) AFTER count,
    ADD COLUMN IF NOT EXISTS `histogram_counts` Array(UInt64) AFTER histogram_bounds
"""

operations = [
    run_sql_with_exceptions(
        ALTER_SERIES_BASE, node_roles=[NodeRole.LOGS], sharded=False, is_alter_on_replicated_table=True
    ),
    run_sql_with_exceptions(
        ALTER_SERIES_TTL, node_roles=[NodeRole.LOGS], sharded=False, is_alter_on_replicated_table=True
    ),
    run_sql_with_exceptions(
        ALTER_SAMPLES_BASE, node_roles=[NodeRole.LOGS], sharded=False, is_alter_on_replicated_table=True
    ),
    run_sql_with_exceptions(
        ALTER_SERIES_DISTRIBUTED, node_roles=[NodeRole.LOGS], sharded=False, is_alter_on_replicated_table=False
    ),
    run_sql_with_exceptions(
        ALTER_SAMPLES_DISTRIBUTED, node_roles=[NodeRole.LOGS], sharded=False, is_alter_on_replicated_table=False
    ),
]
