from prometheus_client import Counter, Gauge, Histogram

BATCHES_PROCESSED_TOTAL = Counter(
    "warehouse_pg_consumer_batches_processed_total",
    "Total batches processed by the Postgres consumer",
    labelnames=["team_id", "schema_id", "status"],
)

BATCH_PROCESSING_DURATION_SECONDS = Histogram(
    "warehouse_pg_consumer_batch_processing_duration_seconds",
    "Duration of individual batch processing",
    labelnames=["team_id", "schema_id"],
    buckets=(0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0, 600.0),
)

BATCH_RETRY_TOTAL = Counter(
    "warehouse_pg_consumer_batch_retry_total",
    "Total batch retry attempts",
    labelnames=["attempt", "error_type"],
)

RUNS_FAILED_TOTAL = Counter(
    "warehouse_pg_consumer_runs_failed_total",
    "Total runs fully failed via fail_run()",
)

POLL_DURATION_SECONDS = Histogram(
    "warehouse_pg_consumer_poll_duration_seconds",
    "Duration of Postgres poll queries",
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)

POLL_BATCHES_FETCHED = Histogram(
    "warehouse_pg_consumer_poll_batches_fetched",
    "Number of batches returned per poll cycle",
    buckets=(0, 1, 5, 10, 25, 50, 100, 250, 500),
)

ACTIVE_GROUPS = Gauge(
    "warehouse_pg_consumer_active_groups",
    "Number of (team_id, schema_id) groups currently being processed",
    multiprocess_mode="livesum",
)

RECOVERY_SWEEPS_TOTAL = Counter(
    "warehouse_pg_consumer_recovery_sweeps_total",
    "Total recovery sweeps executed",
    labelnames=["outcome"],
)
