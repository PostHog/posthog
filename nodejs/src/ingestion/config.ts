import { ConfigOf, defineConfig } from '../config/define-config'
import {
    KAFKA_CLICKHOUSE_HEATMAP_EVENTS,
    KAFKA_EVENTS_JSON,
    KAFKA_EVENTS_PLUGIN_INGESTION,
    KAFKA_EVENTS_PLUGIN_INGESTION_DLQ,
    KAFKA_EVENTS_PLUGIN_INGESTION_OVERFLOW,
} from '../config/kafka-topics'
import { isDevEnv, isProdEnv } from '../utils/env-utils'

export type PersonBatchWritingDbWriteMode = 'NO_ASSERT' | 'ASSERT_VERSION'
export type PersonBatchWritingMode = 'BATCH' | 'SHADOW' | 'NONE'

export type IngestionLane = 'main' | 'overflow' | 'historical' | 'async'

export const ingestionConsumerConfigDefs = defineConfig({
    INGESTION_LANE: (): IngestionLane | null => null,

    // Kafka consumer config
    INGESTION_CONSUMER_GROUP_ID: () => 'events-ingestion-consumer',
    INGESTION_CONSUMER_CONSUME_TOPIC: () => KAFKA_EVENTS_PLUGIN_INGESTION,
    INGESTION_CONSUMER_DLQ_TOPIC: () => KAFKA_EVENTS_PLUGIN_INGESTION_DLQ,
    INGESTION_CONSUMER_OVERFLOW_TOPIC: () => KAFKA_EVENTS_PLUGIN_INGESTION_OVERFLOW,

    // Ingestion pipeline config
    INGESTION_CONCURRENCY: () => 10,
    INGESTION_BATCH_SIZE: () => 500,
    INGESTION_OVERFLOW_ENABLED: () => false,
    INGESTION_FORCE_OVERFLOW_BY_TOKEN_DISTINCT_ID: () => '',
    INGESTION_OVERFLOW_PRESERVE_PARTITION_LOCALITY: () => false,

    // Person batch writing config
    PERSON_BATCH_WRITING_DB_WRITE_MODE: (): PersonBatchWritingDbWriteMode => 'NO_ASSERT',
    PERSON_BATCH_WRITING_USE_BATCH_UPDATES: () => true,
    PERSON_BATCH_WRITING_OPTIMISTIC_UPDATES_ENABLED: () => false,
    PERSON_BATCH_WRITING_MAX_CONCURRENT_UPDATES: () => 10,
    PERSON_BATCH_WRITING_MAX_OPTIMISTIC_UPDATE_RETRIES: () => 5,
    PERSON_BATCH_WRITING_OPTIMISTIC_UPDATE_RETRY_INTERVAL_MS: () => 50,
    PERSONS_PREFETCH_ENABLED: () => false,

    // Person properties config
    PERSON_UPDATE_CALCULATE_PROPERTIES_SIZE: () => 0,
    PERSON_PROPERTIES_DB_CONSTRAINT_LIMIT_BYTES: () => 655360, // 512kb + 128kb
    PERSON_PROPERTIES_TRIM_TARGET_BYTES: () => 512 * 1024,
    PERSON_PROPERTIES_UPDATE_ALL: () => false,
    PERSON_JSONB_SIZE_ESTIMATE_ENABLE: () => 0,

    // Person merge config
    PERSON_MERGE_MOVE_DISTINCT_ID_LIMIT: () => 0,
    PERSON_MERGE_ASYNC_TOPIC: () => '',
    PERSON_MERGE_ASYNC_ENABLED: () => false,
    PERSON_MERGE_SYNC_BATCH_SIZE: () => 0,

    // Group batch writing config
    GROUP_BATCH_WRITING_MAX_CONCURRENT_UPDATES: () => 10,
    GROUP_BATCH_WRITING_MAX_OPTIMISTIC_UPDATE_RETRIES: () => 5,
    GROUP_BATCH_WRITING_OPTIMISTIC_UPDATE_RETRY_INTERVAL_MS: () => 50,

    // Event overflow config
    EVENT_OVERFLOW_BUCKET_CAPACITY: () => 1000,
    EVENT_OVERFLOW_BUCKET_REPLENISH_RATE: () => 1.0,

    // Stateful overflow config
    INGESTION_STATEFUL_OVERFLOW_ENABLED: () => false,
    INGESTION_STATEFUL_OVERFLOW_REDIS_TTL_SECONDS: () => 300, // 5 minutes
    INGESTION_STATEFUL_OVERFLOW_LOCAL_CACHE_TTL_SECONDS: () => 60, // 1 minute

    // Per-token/distinct_id restrictions
    DROP_EVENTS_BY_TOKEN_DISTINCT_ID: () => '',
    SKIP_PERSONS_PROCESSING_BY_TOKEN_DISTINCT_ID: () => '',
    MAX_TEAM_ID_TO_BUFFER_ANONYMOUS_EVENTS_FOR: () => 0,

    // Pipeline step config
    SKIP_UPDATE_EVENT_AND_PROPERTIES_STEP: () => false,
    EVENT_SCHEMA_ENFORCEMENT_ENABLED: () => true,
    KAFKA_BATCH_START_LOGGING_ENABLED: () => false,

    // Clickhouse topics
    CLICKHOUSE_JSON_EVENTS_KAFKA_TOPIC: () => KAFKA_EVENTS_JSON,
    CLICKHOUSE_HEATMAPS_KAFKA_TOPIC: () => KAFKA_CLICKHOUSE_HEATMAP_EVENTS,

    // Cookieless server hash mode config
    COOKIELESS_DISABLED: () => false,
    COOKIELESS_FORCE_STATELESS_MODE: () => false,
    COOKIELESS_DELETE_EXPIRED_LOCAL_SALTS_INTERVAL_MS: () => 60 * 60 * 1000, // 1 hour
    COOKIELESS_SESSION_TTL_SECONDS: () => 60 * 60 * (72 + 24), // 96 hours
    COOKIELESS_SALT_TTL_SECONDS: () => 60 * 60 * (72 + 24), // 96 hours
    COOKIELESS_SESSION_INACTIVITY_MS: () => 30 * 60 * 1000, // 30 minutes
    COOKIELESS_IDENTIFIES_TTL_SECONDS: () =>
        (72 + // max supported ingestion lag in hours
            12 + // max negative timezone in the world
            14 + // max positive timezone in the world
            24) * // amount of time salt is valid in one timezone
        60 *
        60,
    COOKIELESS_REDIS_HOST: () => '',
    COOKIELESS_REDIS_PORT: () => 6379,

    // Property definitions
    PROPERTY_DEFS_CONSUMER_GROUP_ID: () => 'property-defs-consumer',
    PROPERTY_DEFS_CONSUMER_CONSUME_TOPIC: () => KAFKA_EVENTS_JSON,
    PROPERTY_DEFS_CONSUMER_ENABLED_TEAMS: (): string => (isDevEnv() ? '*' : ''),
    PROPERTY_DEFS_WRITE_DISABLED: () => isProdEnv(),

    // Ingestion caching
    DISTINCT_ID_LRU_SIZE: () => 10000,
    EVENT_PROPERTY_LRU_SIZE: () => 10000,
    PERSON_INFO_CACHE_TTL: () => 5 * 60, // 5 min

    // Ingestion pipeline
    INGESTION_PIPELINE: (): string | null => null,
    PLUGIN_SERVER_EVENTS_INGESTION_PIPELINE: (): string | null => null,
})

export type IngestionConsumerConfig = ConfigOf<typeof ingestionConsumerConfigDefs>
