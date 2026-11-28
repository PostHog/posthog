"""The table of precomputed metric buckets on the metrics cluster.

One row is one bucket of one `MetricPrecomputedMetric`, with one entry per kept label set (and histogram layout)
in parallel arrays. A fill that rewrites a bucket inserts a newer `written_at`, and ReplacingMergeTree keeps only
the newest row, so an entry that left the bucket leaves the table. Readers use FINAL. Rows expire 32 days after
their bucket starts, which covers the longest query range plus alignment.
"""

from posthog.clickhouse.table_engines import ReplacingMergeTree, ReplicationScheme

from .metrics4 import _db

METRICS_PRECOMPUTED_BUCKETS_TABLE_NAME = "metrics_precomputed_buckets"


def METRICS_PRECOMPUTED_BUCKETS_TABLE_SQL() -> str:
    # A row can hold 10,000 entries, and a read loads one metric's buckets, so small granules keep a read
    # from decoding other metrics' rows.
    return f"""
CREATE TABLE IF NOT EXISTS {_db()}.{METRICS_PRECOMPUTED_BUCKETS_TABLE_NAME}
(
    `team_id` Int32,
    `precomputed_metric_id` UUID,
    `bucket_start` DateTime,
    `final` Bool,
    `written_at` DateTime64(6),
    `entry_labels` Array(Array(String)),
    `entry_metric_types` Array(LowCardinality(String)),
    `entry_bounds` Array(Array(Float64)),
    `entry_values` Array(Float64),
    `entry_counts` Array(Array(Float64)),
    `entry_fingerprints` Array(Array(UInt64)),
    `entry_fingerprints_truncated` Array(Bool)
)
ENGINE = {ReplacingMergeTree(METRICS_PRECOMPUTED_BUCKETS_TABLE_NAME, replication_scheme=ReplicationScheme.REPLICATED, ver="written_at")}
PARTITION BY toDate(bucket_start)
ORDER BY (team_id, precomputed_metric_id, bucket_start)
TTL bucket_start + toIntervalDay(32)
SETTINGS
    index_granularity = 128,
    ttl_only_drop_parts = 1
"""
