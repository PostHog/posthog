from prometheus_client import Counter, Histogram

MESSAGES_PROCESSED_TOTAL = Counter(
    "warehouse_consumer_messages_processed_total",
    "Total messages processed by the warehouse consumer",
    labelnames=["team_id", "schema_id", "status"],
)

BATCH_PROCESSING_DURATION_SECONDS = Histogram(
    "warehouse_consumer_batch_processing_duration_seconds",
    "Duration of batch processing in the warehouse consumer",
    labelnames=["team_id", "schema_id"],
    buckets=(0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0, 600.0),
)

DLQ_MESSAGES_TOTAL = Counter(
    "warehouse_consumer_dlq_messages_total",
    "Total messages sent to the dead-letter queue",
    labelnames=["team_id", "schema_id", "error_type"],
)

BATCH_RETRY_TOTAL = Counter(
    "warehouse_consumer_batch_retry_total",
    "Total batch retry attempts",
    labelnames=["attempt", "error_type"],
)

BATCH_RETRY_EXHAUSTED_TOTAL = Counter(
    "warehouse_consumer_batch_retry_exhausted_total",
    "Total batches that exhausted all retries",
    labelnames=["error_type"],
)

OFFSET_COMMITS_TOTAL = Counter(
    "warehouse_consumer_offset_commits_total",
    "Total offset commit attempts",
    labelnames=["status"],
)

BATCH_SIZE = Histogram(
    "warehouse_consumer_batch_size",
    "Number of messages in each consumed batch",
    buckets=(1, 5, 10, 25, 50, 100, 250, 500, 1000),
)
