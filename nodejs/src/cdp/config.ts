import type { CommonConfig } from '../common/config'
import { ConfigOf, defineConfig } from '../config/define-config'
import { KAFKA_APP_METRICS_2, KAFKA_EVENTS_JSON, KAFKA_LOG_ENTRIES } from '../config/kafka-topics'
import { isDevEnv, isProdEnv, isTestEnv } from '../utils/env-utils'
import { CyclotronJobQueueKind, CyclotronJobQueueSource } from './types'

export const cdpConfigDefs = defineConfig({
    CDP_WATCHER_COST_ERROR: () => 100,
    CDP_WATCHER_HOG_COST_TIMING: () => 100,
    CDP_WATCHER_HOG_COST_TIMING_LOWER_MS: () => 50,
    CDP_WATCHER_HOG_COST_TIMING_UPPER_MS: () => 550,
    CDP_WATCHER_ASYNC_COST_TIMING: () => 20,
    CDP_WATCHER_ASYNC_COST_TIMING_LOWER_MS: () => 100,
    CDP_WATCHER_ASYNC_COST_TIMING_UPPER_MS: () => 5000,
    CDP_WATCHER_THRESHOLD_DEGRADED: () => 0.8,
    CDP_WATCHER_BUCKET_SIZE: () => 10000,
    CDP_WATCHER_TTL: () => 60 * 60 * 24,
    CDP_WATCHER_STATE_LOCK_TTL: () => 60,
    CDP_WATCHER_REFILL_RATE: () => 10,
    CDP_WATCHER_DISABLED_TEMPORARY_TTL: () => 60 * 10,
    CDP_WATCHER_DISABLED_TEMPORARY_MAX_COUNT: () => 3,
    CDP_WATCHER_AUTOMATICALLY_DISABLE_FUNCTIONS: () => !isProdEnv(),
    CDP_WATCHER_SEND_EVENTS: () => !isProdEnv(),
    CDP_WATCHER_OBSERVE_RESULTS_BUFFER_TIME_MS: () => 500,
    CDP_WATCHER_OBSERVE_RESULTS_BUFFER_MAX_RESULTS: () => 500,
    CDP_RATE_LIMITER_BUCKET_SIZE: () => 100,
    CDP_RATE_LIMITER_REFILL_RATE: () => 1,
    CDP_RATE_LIMITER_TTL: () => 60 * 60 * 24,
    CDP_HOG_FILTERS_TELEMETRY_TEAMS: () => '',
    CDP_CYCLOTRON_JOB_QUEUE_CONSUMER_KIND: (): CyclotronJobQueueKind => 'hog',
    CDP_CYCLOTRON_JOB_QUEUE_CONSUMER_MODE: (): CyclotronJobQueueSource => 'kafka',
    CDP_CYCLOTRON_JOB_QUEUE_PRODUCER_MAPPING: () => '*:kafka',
    CDP_CYCLOTRON_JOB_QUEUE_PRODUCER_TEAM_MAPPING: () => '',
    CDP_CYCLOTRON_JOB_QUEUE_PRODUCER_FORCE_SCHEDULED_TO_POSTGRES: () => false,

    CDP_LEGACY_EVENT_CONSUMER_GROUP_ID: () => 'clickhouse-plugin-server-async-onevent',
    CDP_LEGACY_EVENT_CONSUMER_TOPIC: () => KAFKA_EVENTS_JSON,
    CDP_LEGACY_EVENT_CONSUMER_INCLUDE_WEBHOOKS: () => false,

    CDP_CYCLOTRON_BATCH_DELAY_MS: () => 50,
    CDP_CYCLOTRON_INSERT_MAX_BATCH_SIZE: () => 100,
    CDP_CYCLOTRON_INSERT_PARALLEL_BATCHES: () => true,
    CDP_CYCLOTRON_COMPRESS_VM_STATE: () => !isProdEnv(),
    CDP_CYCLOTRON_USE_BULK_COPY_JOB: () => !isProdEnv(),
    CDP_CYCLOTRON_COMPRESS_KAFKA_DATA: () => true,
    CDP_REDIS_HOST: () => '127.0.0.1',
    CDP_REDIS_PORT: () => 6379,
    CDP_REDIS_PASSWORD: () => '',

    CDP_EVENT_PROCESSOR_EXECUTE_FIRST_STEP: () => true,
    CDP_GOOGLE_ADWORDS_DEVELOPER_TOKEN: () => '',
    CDP_FETCH_RETRIES: () => 3,
    CDP_FETCH_BACKOFF_BASE_MS: () => 1000,
    CDP_FETCH_BACKOFF_MAX_MS: () => 30000,
    CDP_OVERFLOW_QUEUE_ENABLED: () => false,
    OUTBOUND_PROXY_URL: () => '',
    OUTBOUND_PROXY_ENABLED: () => false,

    HOG_FUNCTION_MONITORING_APP_METRICS_TOPIC: () => KAFKA_APP_METRICS_2,
    HOG_FUNCTION_MONITORING_LOG_ENTRIES_TOPIC: () => KAFKA_LOG_ENTRIES,

    CDP_EMAIL_TRACKING_URL: () => 'http://localhost:8010',

    // Cyclotron (CDP job queue)
    CYCLOTRON_DATABASE_URL: (): string =>
        isTestEnv()
            ? 'postgres://posthog:posthog@localhost:5432/test_cyclotron'
            : 'postgres://posthog:posthog@localhost:5432/cyclotron',
    CYCLOTRON_SHARD_DEPTH_LIMIT: () => 1000000,
    CYCLOTRON_SHADOW_DATABASE_URL: (): string =>
        isTestEnv()
            ? 'postgres://posthog:posthog@localhost:5432/test_cyclotron_shadow'
            : 'postgres://posthog:posthog@localhost:5432/cyclotron_shadow',
    CDP_CYCLOTRON_SHADOW_WRITE_ENABLED: () => false,
    CDP_CYCLOTRON_TEST_SEEK_LATENCY: () => false,
    CDP_CYCLOTRON_TEST_SEEK_MAX_OFFSET: () => 50_000_000,
    CDP_CYCLOTRON_TEST_FETCH_INDIVIDUAL_COUNT: () => 500,
    CDP_CYCLOTRON_TEST_FETCH_BATCH_COUNT: () => 10,
    CDP_CYCLOTRON_TEST_FETCH_BATCH_SIZE: () => 50,
    CDP_CYCLOTRON_WARPSTREAM_HTTP_URL: () => '',

    // SES (Workflows email sending)
    SES_ENDPOINT: (): string => (isTestEnv() || isDevEnv() ? 'http://localhost:4566' : ''),
    SES_ACCESS_KEY_ID: (): string => (isTestEnv() || isDevEnv() ? 'test' : ''),
    SES_SECRET_ACCESS_KEY: (): string => (isTestEnv() || isDevEnv() ? 'test' : ''),
    SES_REGION: (): string => (isTestEnv() || isDevEnv() ? 'us-east-1' : ''),

    // Temporal (LLM analytics)
    TEMPORAL_HOST: () => 'localhost',
    TEMPORAL_PORT: (): string | undefined => '7233',
    TEMPORAL_NAMESPACE: () => 'default',
    TEMPORAL_CLIENT_ROOT_CA: (): string | undefined => undefined,
    TEMPORAL_CLIENT_CERT: (): string | undefined => undefined,
    TEMPORAL_CLIENT_KEY: (): string | undefined => undefined,

    // Destination migration diffing
    DESTINATION_MIGRATION_DIFFING_ENABLED: () => false,

    CDP_BATCH_WORKFLOW_PRODUCER_BATCH_SIZE: () => 1,

    APP_METRICS_FLUSH_FREQUENCY_MS: (): number => (isTestEnv() ? 5 : 20_000),
    APP_METRICS_FLUSH_MAX_QUEUE_SIZE: (): number => (isTestEnv() ? 5 : 1000),
})

// DISABLE_OPENTELEMETRY_TRACING is owned by CommonConfig but historically part of CdpConfig
export type CdpConfig = ConfigOf<typeof cdpConfigDefs> & Pick<CommonConfig, 'DISABLE_OPENTELEMETRY_TRACING'>
