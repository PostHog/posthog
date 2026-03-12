export type ErrorTrackingConsumerConfig = {
    ERROR_TRACKING_CONSUMER_GROUP_ID: string
    ERROR_TRACKING_CONSUMER_CONSUME_TOPIC: string
    ERROR_TRACKING_CONSUMER_DLQ_TOPIC: string
    ERROR_TRACKING_CONSUMER_OVERFLOW_TOPIC: string
    ERROR_TRACKING_CONSUMER_OUTPUT_TOPIC: string
    ERROR_TRACKING_CYMBAL_BASE_URL: string
    ERROR_TRACKING_CYMBAL_TIMEOUT_MS: number

    /** Token bucket capacity for rate limiting (events per token:distinct_id) */
    ERROR_TRACKING_OVERFLOW_BUCKET_CAPACITY: number
    /** Token bucket replenish rate (events per second) */
    ERROR_TRACKING_OVERFLOW_BUCKET_REPLENISH_RATE: number
    /** When true, uses Redis to coordinate overflow state across pods */
    ERROR_TRACKING_STATEFUL_OVERFLOW_ENABLED: boolean
    /** TTL in seconds for Redis overflow flags */
    ERROR_TRACKING_STATEFUL_OVERFLOW_REDIS_TTL_SECONDS: number
    /** TTL in seconds for local cache entries */
    ERROR_TRACKING_STATEFUL_OVERFLOW_LOCAL_CACHE_TTL_SECONDS: number
}
