import { ConfigOf, defineConfig } from '../config/define-config'
import { isDevEnv, isProdEnv, isTestEnv } from '../utils/env-utils'

export enum KafkaSecurityProtocol {
    Plaintext = 'PLAINTEXT',
    SaslPlaintext = 'SASL_PLAINTEXT',
    Ssl = 'SSL',
    SaslSsl = 'SASL_SSL',
}

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
    recordings_blob_ingestion_v2_overflow = 'recordings-blob-ingestion-v2-overflow',
    cdp_processed_events = 'cdp-processed-events',
    cdp_person_updates = 'cdp-person-updates',
    cdp_data_warehouse_events = 'cdp-data-warehouse-events',
    cdp_internal_events = 'cdp-internal-events',
    cdp_cyclotron_worker = 'cdp-cyclotron-worker',
    cdp_precalculated_filters = 'cdp-precalculated-filters',
    cdp_cohort_membership = 'cdp-cohort-membership',
    cdp_cyclotron_worker_hogflow = 'cdp-cyclotron-worker-hogflow',
    cdp_api = 'cdp-api',
    cdp_legacy_on_event = 'cdp-legacy-on-event',
    evaluation_scheduler = 'evaluation-scheduler',
    ingestion_logs = 'ingestion-logs',
    cdp_batch_hogflow_requests = 'cdp-batch-hogflow-requests',
    cdp_cyclotron_shadow_worker = 'cdp-cyclotron-shadow-worker',
    recording_api = 'recording-api',
}

export const stringToPluginServerMode = Object.fromEntries(
    Object.entries(PluginServerMode).map(([key, value]) => [
        value,
        PluginServerMode[key as keyof typeof PluginServerMode],
    ])
) as Record<string, PluginServerMode>

export const commonConfigDefs = defineConfig({
    // Observability
    CONTINUOUS_PROFILING_ENABLED: () => false,
    PYROSCOPE_SERVER_ADDRESS: () => '',
    PYROSCOPE_APPLICATION_NAME: () => '',
    INSTRUMENT_THREAD_PERFORMANCE: () => false,
    OTEL_EXPORTER_OTLP_ENDPOINT: (): string => (isDevEnv() ? 'http://localhost:4317' : ''),
    OTEL_SDK_DISABLED: () => !isDevEnv(),
    OTEL_TRACES_SAMPLER_ARG: () => 1,
    OTEL_MAX_SPANS_PER_GROUP: () => 2,
    OTEL_MIN_SPAN_DURATION_MS: () => 50,
    DISABLE_OPENTELEMETRY_TRACING: () => false,

    // Tasks
    TASKS_PER_WORKER: () => 10,
    TASK_TIMEOUT: () => 30,

    // Database
    DATABASE_URL: (): string =>
        isTestEnv()
            ? 'postgres://posthog:posthog@localhost:5432/test_posthog'
            : isDevEnv()
              ? 'postgres://posthog:posthog@localhost:5432/posthog'
              : '',
    DATABASE_READONLY_URL: () => '',
    PERSONS_DATABASE_URL: (): string =>
        isTestEnv()
            ? 'postgres://posthog:posthog@localhost:5432/test_persons'
            : isDevEnv()
              ? 'postgres://posthog:posthog@localhost:5432/posthog_persons'
              : '',
    BEHAVIORAL_COHORTS_DATABASE_URL: (): string =>
        isTestEnv()
            ? 'postgres://posthog:posthog@localhost:5432/test_behavioral_cohorts'
            : isDevEnv()
              ? 'postgres://posthog:posthog@localhost:5432/behavioral_cohorts'
              : '',
    PERSONS_READONLY_DATABASE_URL: (): string =>
        isTestEnv()
            ? 'postgres://posthog:posthog@localhost:5432/test_persons'
            : isDevEnv()
              ? 'postgres://posthog:posthog@localhost:5432/posthog_persons'
              : '',
    PLUGIN_STORAGE_DATABASE_URL: () => '',
    POSTGRES_CONNECTION_POOL_SIZE: () => 10,
    POSTHOG_DB_NAME: (): string | null => null,
    POSTHOG_DB_USER: () => 'postgres',
    POSTHOG_DB_PASSWORD: () => '',
    POSTHOG_POSTGRES_HOST: () => 'localhost',
    POSTHOG_POSTGRES_PORT: () => 5432,
    POSTGRES_BEHAVIORAL_COHORTS_HOST: () => 'localhost',
    POSTGRES_BEHAVIORAL_COHORTS_USER: () => 'postgres',
    POSTGRES_BEHAVIORAL_COHORTS_PASSWORD: () => '',

    // Redis
    REDIS_URL: () => 'redis://127.0.0.1',
    INGESTION_REDIS_HOST: () => '',
    INGESTION_REDIS_PORT: () => 6379,
    POSTHOG_REDIS_PASSWORD: () => '',
    POSTHOG_REDIS_HOST: () => '',
    POSTHOG_REDIS_PORT: () => 6379,
    REDIS_POOL_MIN_SIZE: () => 1,
    REDIS_POOL_MAX_SIZE: () => 3,

    // Kafka consumer base
    CONSUMER_BATCH_SIZE: () => 500,
    CONSUMER_MAX_HEARTBEAT_INTERVAL_MS: () => 30_000,
    CONSUMER_LOOP_STALL_THRESHOLD_MS: () => 60_000,
    CONSUMER_LOG_STATS_LEVEL: (): LogLevel => 'debug',
    CONSUMER_LOOP_BASED_HEALTH_CHECK: () => false,
    CONSUMER_MAX_BACKGROUND_TASKS: () => 1,
    CONSUMER_WAIT_FOR_BACKGROUND_TASKS_ON_REBALANCE: () => false,
    CONSUMER_AUTO_CREATE_TOPICS: () => true,

    // Kafka
    KAFKA_HOSTS: () => 'kafka:9092', // KEEP IN SYNC WITH posthog/settings/data_stores.py
    KAFKA_SECURITY_PROTOCOL: (): KafkaSecurityProtocol | undefined => undefined,
    KAFKA_CLIENT_RACK: (): string | undefined => undefined,
    KAFKA_CLIENT_CERT_B64: (): string | undefined => undefined,
    KAFKA_CLIENT_CERT_KEY_B64: (): string | undefined => undefined,
    KAFKA_TRUSTED_CERT_B64: (): string | undefined => undefined,
    KAFKA_SASL_MECHANISM: (): KafkaSaslMechanism | undefined => undefined,
    KAFKA_SASL_USER: (): string | undefined => undefined,
    KAFKA_SASL_PASSWORD: (): string | undefined => undefined,

    // Server
    BASE_DIR: () => '..',
    LOG_LEVEL: (): LogLevel => (isTestEnv() ? 'warn' : 'info'),
    HTTP_SERVER_PORT: () => 6738,
    SCHEDULE_LOCK_TTL: () => 60,
    HEALTHCHECK_MAX_STALE_SECONDS: () => 2 * 60 * 60, // 2 hours
    KAFKA_HEALTHCHECK_SECONDS: () => 20,
    PLUGIN_SERVER_MODE: (): PluginServerMode | null => null,
    NODEJS_CAPABILITY_GROUPS: (): string | null => null,
    PLUGIN_LOAD_SEQUENTIALLY: () => false,
    CLOUD_DEPLOYMENT: (): string | null => null,
    RELOAD_PLUGIN_JITTER_MAX_MS: () => 60000,

    // Shared services
    SITE_URL: (): string => (isDevEnv() ? 'http://localhost:8000' : ''),
    ENCRYPTION_SALT_KEYS: (): string => (isDevEnv() || isTestEnv() ? '00beef0000beef0000beef0000beef00' : ''),
    CAPTURE_INTERNAL_URL: (): string =>
        isProdEnv() ? 'http://capture.posthog.svc.cluster.local:3000/capture' : 'http://localhost:8010/capture',
    CAPTURE_CONFIG_REDIS_HOST: (): string | null => null,
    MMDB_FILE_LOCATION: () => '../share/GeoLite2-City.mmdb',
    LAZY_LOADER_DEFAULT_BUFFER_MS: () => 10,
    LAZY_LOADER_MAX_SIZE: () => 100_000,
    INTERNAL_API_BASE_URL: (): string =>
        isProdEnv() ? 'http://posthog-web-django.posthog.svc.cluster.local:8000' : 'http://localhost:8000',
    INTERNAL_API_SECRET: (): string => (isProdEnv() ? '' : 'posthog123'),
    EXTERNAL_REQUEST_TIMEOUT_MS: () => 3000,
    EXTERNAL_REQUEST_CONNECT_TIMEOUT_MS: () => 3000,
    EXTERNAL_REQUEST_KEEP_ALIVE_TIMEOUT_MS: () => 10000,
    EXTERNAL_REQUEST_CONNECTIONS: () => 500,

    // PostHog analytics
    POSTHOG_API_KEY: () => '',
    POSTHOG_HOST_URL: () => 'http://localhost:8010',
    OTEL_SERVICE_NAME: (): string | null => null,
    OTEL_SERVICE_ENVIRONMENT: (): string | null => null,

    // Shared between ingestion and CDP
    CDP_HOG_WATCHER_SAMPLE_RATE: () => 0,

    // Pod termination
    POD_TERMINATION_ENABLED: () => false,
    POD_TERMINATION_BASE_TIMEOUT_MINUTES: () => 30,
    POD_TERMINATION_JITTER_MINUTES: () => 45,
})

export type CommonConfig = ConfigOf<typeof commonConfigDefs>
