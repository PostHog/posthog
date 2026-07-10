import { isDevEnv, isProdEnv, isTestEnv } from '~/common/utils/env-utils'

import type { BaseServerConfig } from '../servers/base-server'

export const DEFAULT_HTTP_SERVER_PORT = 6738

// Public dev-only default for the internal API secret. Never accepted as a valid secret in production
// (mirrors LOCAL_DEV_INTERNAL_API_SECRET on the Django side).
export const LOCAL_DEV_INTERNAL_API_SECRET = 'posthog123'

export enum KafkaSaslMechanism {
    Plain = 'plain',
    ScramSha256 = 'scram-sha-256',
    ScramSha512 = 'scram-sha-512',
}

export type LogLevel = 'debug' | 'info' | 'warn' | 'error'

export enum PluginServerMode {
    ingestion_v2 = 'ingestion-v2',
    local_cdp = 'local-cdp',
    recordings_blob_ingestion_v2 = 'recordings-blob-ingestion-v2',
    // TODO: Remove once charts deploy with mode=recordings-blob-ingestion-v2 for overflow pods
    recordings_blob_ingestion_v2_overflow = 'recordings-blob-ingestion-v2-overflow',
    recordings_blob_ingestion_v2_ml_mirror = 'recordings-blob-ingestion-v2-ml-mirror',
    recordings_blob_ingestion_v2_ml_parquet_sink = 'recordings-blob-ingestion-v2-ml-parquet-sink',
    recordings_blob_ingestion_v2_ml_image_scrub = 'recordings-blob-ingestion-v2-ml-image-scrub',
    cdp_processed_events = 'cdp-processed-events',
    cdp_person_updates = 'cdp-person-updates',
    cdp_data_warehouse_events = 'cdp-data-warehouse-events',
    cdp_internal_events = 'cdp-internal-events',
    cdp_cyclotron_worker = 'cdp-cyclotron-worker',
    cdp_precalculated_filters = 'cdp-precalculated-filters',
    cdp_hogflow_subscription_matcher = 'cdp-hogflow-subscription-matcher',
    cdp_cohort_membership = 'cdp-cohort-membership',
    cdp_cyclotron_worker_hogflow = 'cdp-cyclotron-worker-hogflow',
    cdp_cyclotron_worker_hogflow_legacy_pg = 'cdp-cyclotron-worker-hogflow-legacy-pg',
    cdp_cyclotron_worker_email = 'cdp-cyclotron-worker-email',
    cdp_cyclotron_worker_email_legacy_pg = 'cdp-cyclotron-worker-email-legacy-pg',
    cdp_api = 'cdp-api',
    cdp_legacy_on_event = 'cdp-legacy-on-event',
    evaluation_scheduler = 'evaluation-scheduler',
    ingestion_logs = 'ingestion-logs',
    ingestion_error_tracking = 'ingestion-errortracking',
    ingestion_metrics = 'ingestion-metrics',
    cdp_cyclotron_worker_batch_resolve = 'cdp-cyclotron-worker-batch-resolve',
    cdp_cyclotron_v2_janitor = 'cdp-cyclotron-v2-janitor',
    cdp_rerun_worker = 'cdp-rerun-worker',
    recording_api = 'recording-api',
    ingestion_v2_combined = 'ingestion-v2-combined',
    ingestion_traces = 'ingestion-traces',
    cdp_hogflow_scheduler = 'cdp-hogflow-scheduler',
    ingestion_api = 'ingestion-api',
}

export const stringToPluginServerMode = Object.fromEntries(
    Object.entries(PluginServerMode).map(([key, value]) => [
        value,
        PluginServerMode[key as keyof typeof PluginServerMode],
    ])
) as Record<string, PluginServerMode>

export type CommonConfig = BaseServerConfig & {
    // Observability
    OTEL_EXPORTER_OTLP_ENDPOINT: string
    OTEL_SDK_DISABLED: boolean
    OTEL_TRACES_SAMPLER_ARG: number
    OTEL_MAX_SPANS_PER_GROUP: number
    OTEL_MIN_SPAN_DURATION_MS: number
    /** OTLP metrics push target (e.g. capture-logs /v1/metrics); empty disables the meter provider. */
    OTEL_METRICS_EXPORT_URL: string
    /** Capture token identifying the team that receives the pushed metrics. */
    OTEL_METRICS_EXPORT_TOKEN: string
    OTEL_METRICS_EXPORT_INTERVAL_MS: number
    DISABLE_OPENTELEMETRY_TRACING: boolean

    // Tasks
    TASK_TIMEOUT: number

    // Database
    DATABASE_URL: string
    DATABASE_READONLY_URL: string
    PERSONS_DATABASE_URL: string
    BEHAVIORAL_COHORTS_DATABASE_URL: string
    PERSONS_READONLY_DATABASE_URL: string
    PLUGIN_STORAGE_DATABASE_URL: string
    POSTGRES_CONNECTION_POOL_SIZE: number
    POSTHOG_DB_NAME: string | null
    POSTHOG_DB_USER: string
    POSTHOG_DB_PASSWORD: string
    POSTHOG_POSTGRES_HOST: string
    POSTHOG_POSTGRES_PORT: number
    POSTGRES_BEHAVIORAL_COHORTS_HOST: string
    POSTGRES_BEHAVIORAL_COHORTS_USER: string
    POSTGRES_BEHAVIORAL_COHORTS_PASSWORD: string

    // PersonHog gRPC
    PERSONHOG_ENABLED: boolean
    PERSONHOG_ADDR: string
    PERSONHOG_GROUPS_ROLLOUT_PERCENTAGE: number
    PERSONHOG_GROUPS_ROLLOUT_TEAM_IDS: string
    PERSONHOG_PERSONS_ROLLOUT_PERCENTAGE: number
    PERSONHOG_PERSONS_ROLLOUT_TEAM_IDS: string
    PERSONHOG_TLS: boolean
    PERSONHOG_TIMEOUT_MS: number
    PERSONHOG_READ_MAX_BYTES: number
    PERSONHOG_WRITE_MAX_BYTES: number
    PERSONHOG_PING_INTERVAL_MS: number
    PERSONHOG_PING_TIMEOUT_MS: number
    PERSONHOG_PING_IDLE_CONNECTION: boolean
    PERSONHOG_IDLE_CONNECTION_TIMEOUT_MS: number
    PERSONHOG_STATE_MONITOR_POLL_INTERVAL_MS: number

    // Redis
    REDIS_URL: string
    INGESTION_REDIS_HOST: string
    INGESTION_REDIS_PORT: number
    POSTHOG_REDIS_PASSWORD: string
    POSTHOG_REDIS_HOST: string
    POSTHOG_REDIS_PORT: number
    REDIS_POOL_MIN_SIZE: number
    REDIS_POOL_MAX_SIZE: number

    // Kafka consumer base
    CONSUMER_BATCH_SIZE: number
    CONSUMER_MAX_HEARTBEAT_INTERVAL_MS: number
    CONSUMER_LOOP_STALL_THRESHOLD_MS: number
    CONSUMER_LOG_STATS_LEVEL: LogLevel
    CONSUMER_LOOP_BASED_HEALTH_CHECK: boolean
    CONSUMER_MAX_BACKGROUND_TASKS: number
    CONSUMER_BACKGROUND_TASK_TIMEOUT_MS: number
    CONSUMER_WAIT_FOR_BACKGROUND_TASKS_ON_REBALANCE: boolean
    CONSUMER_REBALANCE_TIMEOUT_MS: number
    CONSUMER_AUTO_CREATE_TOPICS: boolean
    /**
     * When true, every Kafka consumer in this service uses KafkaConsumerV2; otherwise the
     * legacy KafkaConsumer (v1) is used. Used by `createKafkaConsumer()` in
     * `src/kafka/consumer/index.ts`. Will be removed once v1 is deleted.
     */
    CONSUMER_USE_V2: boolean

    // Kafka
    KAFKA_HOSTS: string
    KAFKA_CLIENT_RACK: string | undefined
    KAFKA_CLIENT_CERT_B64: string | undefined
    KAFKA_CLIENT_CERT_KEY_B64: string | undefined
    KAFKA_TRUSTED_CERT_B64: string | undefined
    KAFKA_SASL_MECHANISM: KafkaSaslMechanism | undefined
    KAFKA_SASL_USER: string | undefined
    KAFKA_SASL_PASSWORD: string | undefined

    // Server
    BASE_DIR: string
    LOG_LEVEL: LogLevel
    SCHEDULE_LOCK_TTL: number
    HEALTHCHECK_MAX_STALE_SECONDS: number
    KAFKA_HEALTHCHECK_SECONDS: number
    PLUGIN_SERVER_MODE: PluginServerMode | null
    NODEJS_CAPABILITY_GROUPS: string | null
    PLUGIN_LOAD_SEQUENTIALLY: boolean
    CLOUD_DEPLOYMENT: string | null
    RELOAD_PLUGIN_JITTER_MAX_MS: number

    // Shared services
    SITE_URL: string
    ENCRYPTION_SALT_KEYS: string
    CAPTURE_INTERNAL_URL: string
    CAPTURE_CONFIG_REDIS_HOST: string | null
    MMDB_FILE_LOCATION: string
    LAZY_LOADER_DEFAULT_BUFFER_MS: number
    LAZY_LOADER_MAX_SIZE: number
    INTERNAL_API_BASE_URL: string
    HOGFLOW_SCHEDULER_POLL_INTERVAL_MS: number
    HOGFLOW_SCHEDULER_MAX_POLL_INTERVAL_MS: number
    HOGFLOW_SCHEDULER_HEALTH_TIMEOUT_MS: number
    EXTERNAL_REQUEST_TIMEOUT_MS: number
    EXTERNAL_REQUEST_CONNECT_TIMEOUT_MS: number
    EXTERNAL_REQUEST_KEEP_ALIVE_TIMEOUT_MS: number
    EXTERNAL_REQUEST_CONNECTIONS: number

    // PostHog analytics
    POSTHOG_API_KEY: string
    POSTHOG_HOST_URL: string
    OTEL_SERVICE_NAME: string | null
    OTEL_SERVICE_ENVIRONMENT: string | null

    // Shared between ingestion and CDP (used by hog transformer in both)
    CDP_HOG_WATCHER_SAMPLE_RATE: number

    // Execute transformations on the Rust HogVM instead of the Node VM. Invocations the Rust VM
    // can't run (unsupported host functions, addon not built) fall back to the Node VM.
    CDP_HOG_RUST_VM_EXECUTION_ENABLED: boolean

    // Event loop yield helper (yieldEventLoopIfNeeded)
    EVENT_LOOP_YIELD_THRESHOLD_MS: number
}

export type ExternalRequestConfig = Pick<
    CommonConfig,
    | 'EXTERNAL_REQUEST_TIMEOUT_MS'
    | 'EXTERNAL_REQUEST_CONNECT_TIMEOUT_MS'
    | 'EXTERNAL_REQUEST_KEEP_ALIVE_TIMEOUT_MS'
    | 'EXTERNAL_REQUEST_CONNECTIONS'
>

export function getExternalRequestConfig(): ExternalRequestConfig {
    return {
        EXTERNAL_REQUEST_TIMEOUT_MS: Number(process.env.EXTERNAL_REQUEST_TIMEOUT_MS ?? 3000),
        EXTERNAL_REQUEST_CONNECT_TIMEOUT_MS: Number(process.env.EXTERNAL_REQUEST_CONNECT_TIMEOUT_MS ?? 3000),
        EXTERNAL_REQUEST_KEEP_ALIVE_TIMEOUT_MS: Number(process.env.EXTERNAL_REQUEST_KEEP_ALIVE_TIMEOUT_MS ?? 10000),
        EXTERNAL_REQUEST_CONNECTIONS: Number(process.env.EXTERNAL_REQUEST_CONNECTIONS ?? 500),
    }
}

export function getDefaultCommonConfig(): CommonConfig {
    return {
        // Observability
        CONTINUOUS_PROFILING_ENABLED: false,
        PYROSCOPE_SERVER_ADDRESS: '',
        PYROSCOPE_APPLICATION_NAME: '',
        INSTRUMENT_THREAD_PERFORMANCE: false,
        OTEL_EXPORTER_OTLP_ENDPOINT: isDevEnv() ? 'http://localhost:4317' : '',
        OTEL_SDK_DISABLED: isDevEnv() ? false : true,
        OTEL_TRACES_SAMPLER_ARG: 1,
        OTEL_MAX_SPANS_PER_GROUP: 2,
        OTEL_MIN_SPAN_DURATION_MS: 50,
        OTEL_METRICS_EXPORT_URL: '',
        OTEL_METRICS_EXPORT_TOKEN: '',
        OTEL_METRICS_EXPORT_INTERVAL_MS: 15000,
        DISABLE_OPENTELEMETRY_TRACING: false,

        // Tasks
        TASK_TIMEOUT: 30,

        // Database
        DATABASE_URL: isTestEnv()
            ? 'postgres://posthog:posthog@localhost:5432/test_posthog'
            : isDevEnv()
              ? 'postgres://posthog:posthog@localhost:5432/posthog'
              : '',
        DATABASE_READONLY_URL: '',
        PERSONS_DATABASE_URL: isTestEnv()
            ? 'postgres://posthog:posthog@localhost:5432/test_persons'
            : isDevEnv()
              ? 'postgres://posthog:posthog@localhost:5432/posthog_persons'
              : '',
        BEHAVIORAL_COHORTS_DATABASE_URL: isTestEnv()
            ? 'postgres://posthog:posthog@localhost:5432/test_behavioral_cohorts'
            : isDevEnv()
              ? 'postgres://posthog:posthog@localhost:5432/behavioral_cohorts'
              : '',
        PERSONS_READONLY_DATABASE_URL: isTestEnv()
            ? 'postgres://posthog:posthog@localhost:5432/test_persons'
            : isDevEnv()
              ? 'postgres://posthog:posthog@localhost:5432/posthog_persons'
              : '',
        PLUGIN_STORAGE_DATABASE_URL: '',
        POSTGRES_CONNECTION_POOL_SIZE: 10,
        POSTHOG_DB_NAME: null,
        POSTHOG_DB_USER: 'postgres',
        POSTHOG_DB_PASSWORD: '',
        POSTHOG_POSTGRES_HOST: 'localhost',
        POSTHOG_POSTGRES_PORT: 5432,
        POSTGRES_BEHAVIORAL_COHORTS_HOST: 'localhost',
        POSTGRES_BEHAVIORAL_COHORTS_USER: 'postgres',
        POSTGRES_BEHAVIORAL_COHORTS_PASSWORD: '',

        // PersonHog gRPC
        PERSONHOG_ENABLED: false,
        PERSONHOG_ADDR: '',
        PERSONHOG_GROUPS_ROLLOUT_PERCENTAGE: 0,
        PERSONHOG_GROUPS_ROLLOUT_TEAM_IDS: '',
        PERSONHOG_PERSONS_ROLLOUT_PERCENTAGE: 0,
        PERSONHOG_PERSONS_ROLLOUT_TEAM_IDS: '',
        PERSONHOG_TLS: false,
        PERSONHOG_TIMEOUT_MS: 3000,
        PERSONHOG_READ_MAX_BYTES: 128 * 1024 * 1024,
        PERSONHOG_WRITE_MAX_BYTES: 4 * 1024 * 1024,
        PERSONHOG_PING_INTERVAL_MS: 30_000,
        PERSONHOG_PING_TIMEOUT_MS: 5_000,
        PERSONHOG_PING_IDLE_CONNECTION: true,
        PERSONHOG_IDLE_CONNECTION_TIMEOUT_MS: 15 * 60 * 1000,
        PERSONHOG_STATE_MONITOR_POLL_INTERVAL_MS: 5_000,

        // Redis
        // ok to connect to localhost over plaintext
        // nosemgrep: trailofbits.generic.redis-unencrypted-transport.redis-unencrypted-transport
        REDIS_URL: 'redis://127.0.0.1',
        INGESTION_REDIS_HOST: '',
        INGESTION_REDIS_PORT: 6379,
        POSTHOG_REDIS_PASSWORD: '',
        POSTHOG_REDIS_HOST: '',
        POSTHOG_REDIS_PORT: 6379,
        REDIS_POOL_MIN_SIZE: 1,
        REDIS_POOL_MAX_SIZE: 3,

        // Kafka consumer base
        CONSUMER_BATCH_SIZE: 500,
        CONSUMER_MAX_HEARTBEAT_INTERVAL_MS: 30_000,
        CONSUMER_LOOP_STALL_THRESHOLD_MS: 60_000,
        CONSUMER_LOG_STATS_LEVEL: 'debug',
        CONSUMER_LOOP_BASED_HEALTH_CHECK: false,
        CONSUMER_MAX_BACKGROUND_TASKS: 1,
        CONSUMER_BACKGROUND_TASK_TIMEOUT_MS: 60_000,
        CONSUMER_WAIT_FOR_BACKGROUND_TASKS_ON_REBALANCE: false,
        CONSUMER_REBALANCE_TIMEOUT_MS: 20_000,
        CONSUMER_AUTO_CREATE_TOPICS: true,
        CONSUMER_USE_V2: false,

        // Kafka
        KAFKA_HOSTS: 'kafka:9092',
        KAFKA_CLIENT_RACK: undefined,
        KAFKA_CLIENT_CERT_B64: undefined,
        KAFKA_CLIENT_CERT_KEY_B64: undefined,
        KAFKA_TRUSTED_CERT_B64: undefined,
        KAFKA_SASL_MECHANISM: undefined,
        KAFKA_SASL_USER: undefined,
        KAFKA_SASL_PASSWORD: undefined,

        // Server
        BASE_DIR: '..',
        LOG_LEVEL: isTestEnv() ? 'warn' : 'info',
        HTTP_SERVER_PORT: DEFAULT_HTTP_SERVER_PORT,
        SCHEDULE_LOCK_TTL: 60,
        HEALTHCHECK_MAX_STALE_SECONDS: 2 * 60 * 60,
        KAFKA_HEALTHCHECK_SECONDS: 20,
        PLUGIN_SERVER_MODE: null,
        NODEJS_CAPABILITY_GROUPS: null,
        PLUGIN_LOAD_SEQUENTIALLY: false,
        CLOUD_DEPLOYMENT: null,
        RELOAD_PLUGIN_JITTER_MAX_MS: 60000,

        // Shared services
        SITE_URL: isDevEnv() ? 'http://localhost:8000' : '',
        ENCRYPTION_SALT_KEYS: isDevEnv() || isTestEnv() ? '00beef0000beef0000beef0000beef00' : '',
        CAPTURE_INTERNAL_URL: isProdEnv()
            ? 'http://capture.posthog.svc.cluster.local:3000/capture'
            : 'http://localhost:8010/capture',
        CAPTURE_CONFIG_REDIS_HOST: null,
        MMDB_FILE_LOCATION: '../share/GeoLite2-City.mmdb',
        LAZY_LOADER_DEFAULT_BUFFER_MS: 10,
        LAZY_LOADER_MAX_SIZE: 100_000,
        INTERNAL_API_BASE_URL: isProdEnv()
            ? 'http://posthog-web-django.posthog.svc.cluster.local:8000'
            : 'http://localhost:8000',
        INTERNAL_API_SECRET: isProdEnv() ? '' : LOCAL_DEV_INTERNAL_API_SECRET,
        INTERNAL_API_SECRET_FALLBACKS: '',
        HOGFLOW_SCHEDULER_POLL_INTERVAL_MS: 60_000,
        HOGFLOW_SCHEDULER_MAX_POLL_INTERVAL_MS: 5 * 60_000,
        HOGFLOW_SCHEDULER_HEALTH_TIMEOUT_MS: 10 * 60_000,
        EXTERNAL_REQUEST_TIMEOUT_MS: 3000,
        EXTERNAL_REQUEST_CONNECT_TIMEOUT_MS: 3000,
        EXTERNAL_REQUEST_KEEP_ALIVE_TIMEOUT_MS: 10000,
        EXTERNAL_REQUEST_CONNECTIONS: 500,

        // PostHog analytics
        POSTHOG_API_KEY: '',
        POSTHOG_HOST_URL: 'http://localhost:8010',
        OTEL_SERVICE_NAME: null,
        OTEL_SERVICE_ENVIRONMENT: null,

        // Shared between ingestion and CDP
        CDP_HOG_WATCHER_SAMPLE_RATE: 0,
        CDP_HOG_RUST_VM_EXECUTION_ENABLED: false,

        // Event loop yield helper
        EVENT_LOOP_YIELD_THRESHOLD_MS: 200,

        // Pod termination
        POD_TERMINATION_ENABLED: false,
        POD_TERMINATION_BASE_TIMEOUT_MINUTES: 30,
        POD_TERMINATION_JITTER_MINUTES: 45,
    }
}
