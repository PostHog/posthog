from prometheus_client import Counter, Gauge, Histogram

WEBHOOK_MESSAGES_BUFFERED_TOTAL = Counter(
    "warehouse_sources_webhook_s3_consumer_messages_buffered_total",
    "Total messages buffered by the webhook S3 consumer",
    labelnames=["team_id"],
)

WEBHOOK_FLUSH_TOTAL = Counter(
    "warehouse_sources_webhook_s3_consumer_flush_total",
    "Total flush cycles executed",
    labelnames=["trigger"],
)

WEBHOOK_PARQUET_WRITES_TOTAL = Counter(
    "warehouse_sources_webhook_s3_consumer_parquet_writes_total",
    "Total parquet files written to S3",
    labelnames=["team_id", "status"],
)

WEBHOOK_PARQUET_WRITE_DURATION_SECONDS = Histogram(
    "warehouse_sources_webhook_s3_consumer_parquet_write_duration_seconds",
    "Duration of parquet file writes to S3",
    buckets=(0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0),
)

WEBHOOK_BUFFER_SIZE_BYTES = Gauge(
    "warehouse_sources_webhook_s3_consumer_buffer_size_bytes",
    "Current buffer size in bytes",
)

WEBHOOK_BUFFER_MESSAGE_COUNT = Gauge(
    "warehouse_sources_webhook_s3_consumer_buffer_message_count",
    "Current number of buffered messages",
)

WEBHOOK_DLQ_MESSAGES_TOTAL = Counter(
    "warehouse_sources_webhook_s3_consumer_dlq_messages_total",
    "Total messages sent to the dead-letter queue",
    labelnames=["error_type"],
)

WEBHOOK_OFFSET_COMMITS_TOTAL = Counter(
    "warehouse_sources_webhook_s3_consumer_offset_commits_total",
    "Total offset commit attempts",
    labelnames=["status"],
)
