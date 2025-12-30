import { PluginsServerConfig, ValueMatcher, stringToPluginServerMode } from '../types'
import { isDevEnv, isProdEnv, isTestEnv, stringToBoolean } from '../utils/env-utils'
import {
    KAFKA_APP_METRICS_2,
    KAFKA_CLICKHOUSE_HEATMAP_EVENTS,
    KAFKA_EVENTS_JSON,
    KAFKA_EVENTS_PLUGIN_INGESTION,
    KAFKA_EVENTS_PLUGIN_INGESTION_DLQ,
    KAFKA_EVENTS_PLUGIN_INGESTION_OVERFLOW,
    KAFKA_LOGS_CLICKHOUSE,
    KAFKA_LOGS_INGESTION,
    KAFKA_LOGS_INGESTION_DLQ,
    KAFKA_LOGS_INGESTION_OVERFLOW,
    KAFKA_LOG_ENTRIES,
} from './kafka-topics'

export const DEFAULT_HTTP_SERVER_PORT = 6738

export const defaultConfig = overrideWithEnv(getDefaultConfig())

export function getDefaultConfig(): PluginsServerConfig {
    return {
        CONTINUOUS_PROFILING_ENABLED: false,
        PYROSCOPE_SERVER_ADDRESS: '',
        PYROSCOPE_APPLICATION_NAME: '',
        INSTRUMENT_THREAD_PERFORMANCE: false,
        OTEL_EXPORTER_OTLP_ENDPOINT: isDevEnv() ? 'http://localhost:4317' : '',
        OTEL_SDK_DISABLED: isDevEnv() ? false : true,
        OTEL_TRACES_SAMPLER_ARG: 1,
        OTEL_MAX_SPANS_PER_GROUP: 2,
        OTEL_MIN_SPAN_DURATION_MS: 50,
        DATABASE_URL: isTestEnv()
            ? 'postgres://posthog:posthog@localhost:5432/test_posthog'
            : isDevEnv()
              ? 'postgres://posthog:posthog@localhost:5432/posthog'
              : '',
        DATABASE_READONLY_URL: '',
        PLUGIN_STORAGE_DATABASE_URL: '',
        PERSONS_DATABASE_URL: isTestEnv()
            ? 'postgres://posthog:posthog@localhost:5432/test_persons'
            : isDevEnv()
              ? 'postgres://posthog:posthog@localhost:5432/posthog_persons'
              : '',
        PERSONS_READONLY_DATABASE_URL: isTestEnv()
            ? 'postgres://posthog:posthog@localhost:5432/test_persons'
            : isDevEnv()
              ? 'postgres://posthog:posthog@localhost:5432/posthog_persons'
              : '',
        BEHAVIORAL_COHORTS_DATABASE_URL: isTestEnv()
            ? 'postgres://posthog:posthog@localhost:5432/test_behavioral_cohorts'
            : isDevEnv()
              ? 'postgres://posthog:posthog@localhost:5432/behavioral_cohorts'
              : '',
        POSTGRES_CONNECTION_POOL_SIZE: 10,
        POSTHOG_DB_NAME: null,
        POSTHOG_DB_USER: 'postgres',
        POSTHOG_DB_PASSWORD: '',
        POSTHOG_POSTGRES_HOST: 'localhost',
        POSTHOG_POSTGRES_PORT: 5432,
        POSTGRES_BEHAVIORAL_COHORTS_HOST: 'localhost',
        POSTGRES_BEHAVIORAL_COHORTS_USER: 'postgres',
        POSTGRES_BEHAVIORAL_COHORTS_PASSWORD: '',
        EVENT_OVERFLOW_BUCKET_CAPACITY: 1000,
        EVENT_OVERFLOW_BUCKET_REPLENISH_RATE: 1.0,
        KAFKA_BATCH_START_LOGGING_ENABLED: false,
        SKIP_UPDATE_EVENT_AND_PROPERTIES_STEP: false,
        CONSUMER_BATCH_SIZE: 500,
        CONSUMER_MAX_HEARTBEAT_INTERVAL_MS: 30_000,
        CONSUMER_LOOP_STALL_THRESHOLD_MS: 60_000, // 1 minute - consider loop stalled after this
        CONSUMER_LOOP_BASED_HEALTH_CHECK: false, // Use consumer loop monitoring for health checks instead of heartbeats
        CONSUMER_MAX_BACKGROUND_TASKS: 1,
        CONSUMER_WAIT_FOR_BACKGROUND_TASKS_ON_REBALANCE: false,
        CONSUMER_AUTO_CREATE_TOPICS: true,
        CONSUMER_LOG_STATS_LEVEL: 'debug',
        KAFKA_HOSTS: 'kafka:9092', // KEEP IN SYNC WITH posthog/settings/data_stores.py
        KAFKA_CLIENT_CERT_B64: undefined,
        KAFKA_CLIENT_CERT_KEY_B64: undefined,
        KAFKA_TRUSTED_CERT_B64: undefined,
        KAFKA_SECURITY_PROTOCOL: undefined,
        KAFKA_SASL_MECHANISM: undefined,
        KAFKA_SASL_USER: undefined,
        KAFKA_SASL_PASSWORD: undefined,
        KAFKA_CLIENT_RACK: undefined,
        APP_METRICS_FLUSH_FREQUENCY_MS: isTestEnv() ? 5 : 20_000,
        APP_METRICS_FLUSH_MAX_QUEUE_SIZE: isTestEnv() ? 5 : 1000,
        // ok to connect to localhost over plaintext
        // nosemgrep: trailofbits.generic.redis-unencrypted-transport.redis-unencrypted-transport
        REDIS_URL: 'redis://127.0.0.1',
        INGESTION_REDIS_HOST: '',
        INGESTION_REDIS_PORT: 6379,
        POSTHOG_REDIS_PASSWORD: '',
        POSTHOG_REDIS_HOST: '',
        POSTHOG_REDIS_PORT: 6379,
        BASE_DIR: '..',
        TASK_TIMEOUT: 30,
        TASKS_PER_WORKER: 10,
        INGESTION_CONCURRENCY: 10,
        INGESTION_BATCH_SIZE: 500,
        INGESTION_OVERFLOW_ENABLED: false,
        INGESTION_FORCE_OVERFLOW_BY_TOKEN_DISTINCT_ID: '',
        INGESTION_OVERFLOW_PRESERVE_PARTITION_LOCALITY: false,
        LOG_LEVEL: isTestEnv() ? 'warn' : 'info',
        HTTP_SERVER_PORT: DEFAULT_HTTP_SERVER_PORT,
        SCHEDULE_LOCK_TTL: 60,
        REDIS_POOL_MIN_SIZE: 1,
        REDIS_POOL_MAX_SIZE: 3,
        MMDB_FILE_LOCATION: '../share/GeoLite2-City.mmdb',
        DISTINCT_ID_LRU_SIZE: 10000,
        EVENT_PROPERTY_LRU_SIZE: 10000,
        HEALTHCHECK_MAX_STALE_SECONDS: 2 * 60 * 60, // 2 hours
        SITE_URL: isDevEnv() ? 'http://localhost:8000' : '',
        TEMPORAL_HOST: 'localhost',
        TEMPORAL_PORT: '7233',
        TEMPORAL_NAMESPACE: 'default',
        TEMPORAL_CLIENT_ROOT_CA: undefined,
        TEMPORAL_CLIENT_CERT: undefined,
        TEMPORAL_CLIENT_KEY: undefined,
        CLICKHOUSE_JSON_EVENTS_KAFKA_TOPIC: KAFKA_EVENTS_JSON,
        CLICKHOUSE_HEATMAPS_KAFKA_TOPIC: KAFKA_CLICKHOUSE_HEATMAP_EVENTS,
        PERSON_INFO_CACHE_TTL: 5 * 60, // 5 min
        KAFKA_HEALTHCHECK_SECONDS: 20,
        PLUGIN_SERVER_MODE: null,
        PLUGIN_SERVER_EVENTS_INGESTION_PIPELINE: null,
        PLUGIN_LOAD_SEQUENTIALLY: false,
        MAX_TEAM_ID_TO_BUFFER_ANONYMOUS_EVENTS_FOR: 0,
        CLOUD_DEPLOYMENT: null,
        EXTERNAL_REQUEST_TIMEOUT_MS: 3000, // 3 seconds
        EXTERNAL_REQUEST_CONNECT_TIMEOUT_MS: 3000, // 3 seconds
        EXTERNAL_REQUEST_KEEP_ALIVE_TIMEOUT_MS: 10000, // 10 seconds
        EXTERNAL_REQUEST_CONNECTIONS: 500, // 500 connections
        DROP_EVENTS_BY_TOKEN_DISTINCT_ID: '',
        SKIP_PERSONS_PROCESSING_BY_TOKEN_DISTINCT_ID: '',
        PIPELINE_STEP_STALLED_LOG_TIMEOUT: 30,
        RELOAD_PLUGIN_JITTER_MAX_MS: 60000,
        CAPTURE_CONFIG_REDIS_HOST: null,
        LAZY_LOADER_DEFAULT_BUFFER_MS: 10,
        LAZY_LOADER_MAX_SIZE: 100_000, // Maximum entries per cache before LRU eviction
        CAPTURE_INTERNAL_URL: isProdEnv()
            ? 'http://capture.posthog.svc.cluster.local:3000/capture'
            : 'http://localhost:8010/capture',

        // posthog
        POSTHOG_API_KEY: '',
        POSTHOG_HOST_URL: 'http://localhost:8010',

        SESSION_RECORDING_LOCAL_DIRECTORY: '.tmp/sessions',
        // NOTE: 10 minutes
        SESSION_RECORDING_MAX_BUFFER_AGE_SECONDS: 60 * 10,
        SESSION_RECORDING_BUFFER_AGE_JITTER: 0.3,
        SESSION_RECORDING_BUFFER_AGE_IN_MEMORY_MULTIPLIER: 1.2,
        SESSION_RECORDING_MAX_BUFFER_SIZE_KB: 1024 * 50, // 50MB
        SESSION_RECORDING_REMOTE_FOLDER: 'session_recordings',
        SESSION_RECORDING_REDIS_PREFIX: '@posthog/replay/',
        SESSION_RECORDING_PARTITION_REVOKE_OPTIMIZATION: false,
        SESSION_RECORDING_PARALLEL_CONSUMPTION: false,
        POSTHOG_SESSION_RECORDING_REDIS_HOST: undefined,
        POSTHOG_SESSION_RECORDING_REDIS_PORT: undefined,
        SESSION_RECORDING_CONSOLE_LOGS_INGESTION_ENABLED: true,
        SESSION_RECORDING_REPLAY_EVENTS_INGESTION_ENABLED: true,
        SESSION_RECORDING_DEBUG_PARTITION: '',
        SESSION_RECORDING_MAX_PARALLEL_FLUSHES: 10,
        SESSION_RECORDING_OVERFLOW_ENABLED: false,
        SESSION_RECORDING_OVERFLOW_BUCKET_REPLENISH_RATE: 5_000_000, // 5MB/second uncompressed, sustained
        SESSION_RECORDING_OVERFLOW_BUCKET_CAPACITY: 200_000_000, // 200MB burst
        SESSION_RECORDING_OVERFLOW_MIN_PER_BATCH: 1_000_000, // All sessions consume at least 1MB/batch, to penalise poor batching

        ENCRYPTION_SALT_KEYS: isDevEnv() || isTestEnv() ? '00beef0000beef0000beef0000beef00' : '',

        // CDP
        CDP_WATCHER_COST_ERROR: 100,
        CDP_WATCHER_HOG_COST_TIMING: 100,
        CDP_WATCHER_HOG_COST_TIMING_LOWER_MS: 50,
        CDP_WATCHER_HOG_COST_TIMING_UPPER_MS: 550,
        CDP_WATCHER_ASYNC_COST_TIMING: 20,
        CDP_WATCHER_ASYNC_COST_TIMING_LOWER_MS: 100,
        CDP_WATCHER_ASYNC_COST_TIMING_UPPER_MS: 5000,
        CDP_WATCHER_THRESHOLD_DEGRADED: 0.8,
        CDP_WATCHER_BUCKET_SIZE: 10000,
        CDP_WATCHER_DISABLED_TEMPORARY_TTL: 60 * 10, // 5 minutes
        CDP_WATCHER_TTL: 60 * 60 * 24, // This is really long as it is essentially only important to make sure the key is eventually deleted
        CDP_WATCHER_REFILL_RATE: 10,
        CDP_WATCHER_STATE_LOCK_TTL: 60, // 1 minute
        CDP_WATCHER_DISABLED_TEMPORARY_MAX_COUNT: 3,
        CDP_WATCHER_SEND_EVENTS: isProdEnv() ? false : true,
        CDP_WATCHER_OBSERVE_RESULTS_BUFFER_TIME_MS: 500,
        CDP_WATCHER_OBSERVE_RESULTS_BUFFER_MAX_RESULTS: 500,
        CDP_RATE_LIMITER_BUCKET_SIZE: 100,
        CDP_RATE_LIMITER_REFILL_RATE: 1, // per second request rate limit
        CDP_RATE_LIMITER_TTL: 60 * 60 * 24, // This is really long as it is essentially only important to make sure the key is eventually deleted
        CDP_HOG_FILTERS_TELEMETRY_TEAMS: '',
        DISABLE_OPENTELEMETRY_TRACING: false, // Disable OpenTelemetry spans for better performance (keeps metrics and timeouts)
        CDP_REDIS_PASSWORD: '',
        CDP_EVENT_PROCESSOR_EXECUTE_FIRST_STEP: true,
        CDP_REDIS_HOST: '127.0.0.1',
        CDP_REDIS_PORT: 6479,
        CDP_CYCLOTRON_BATCH_DELAY_MS: 50,
        CDP_GOOGLE_ADWORDS_DEVELOPER_TOKEN: '',
        CDP_CYCLOTRON_JOB_QUEUE_CONSUMER_KIND: 'hog',
        CDP_CYCLOTRON_JOB_QUEUE_CONSUMER_MODE: 'kafka',
        CDP_CYCLOTRON_JOB_QUEUE_PRODUCER_MAPPING: '*:kafka',
        CDP_CYCLOTRON_JOB_QUEUE_PRODUCER_TEAM_MAPPING: '',
        CDP_CYCLOTRON_JOB_QUEUE_PRODUCER_FORCE_SCHEDULED_TO_POSTGRES: false,
        CDP_CYCLOTRON_INSERT_MAX_BATCH_SIZE: 100,
        CDP_CYCLOTRON_INSERT_PARALLEL_BATCHES: true,
        CDP_CYCLOTRON_COMPRESS_VM_STATE: isProdEnv() ? false : true,
        CDP_CYCLOTRON_USE_BULK_COPY_JOB: isProdEnv() ? false : true,
        CDP_CYCLOTRON_COMPRESS_KAFKA_DATA: true,
        CDP_HOG_WATCHER_SAMPLE_RATE: 0, // default is off

        CDP_FETCH_RETRIES: 3,
        CDP_FETCH_BACKOFF_BASE_MS: 1000,
        CDP_FETCH_BACKOFF_MAX_MS: 30000,
        CDP_OVERFLOW_QUEUE_ENABLED: false,
        CDP_WATCHER_AUTOMATICALLY_DISABLE_FUNCTIONS: isProdEnv() ? false : true, // For prod we primarily use overflow and some more manual control
        CDP_EMAIL_TRACKING_URL: 'http://localhost:8010',

        CDP_LEGACY_EVENT_CONSUMER_GROUP_ID: 'clickhouse-plugin-server-async-onevent',
        CDP_LEGACY_EVENT_CONSUMER_TOPIC: KAFKA_EVENTS_JSON,
        CDP_LEGACY_EVENT_CONSUMER_INCLUDE_WEBHOOKS: false,

        HOG_FUNCTION_MONITORING_APP_METRICS_TOPIC: KAFKA_APP_METRICS_2,
        HOG_FUNCTION_MONITORING_LOG_ENTRIES_TOPIC: KAFKA_LOG_ENTRIES,

        // Destination Migration Diffing
        DESTINATION_MIGRATION_DIFFING_ENABLED: false,

        // Cyclotron
        CYCLOTRON_DATABASE_URL: isTestEnv()
            ? 'postgres://posthog:posthog@localhost:5432/test_cyclotron'
            : 'postgres://posthog:posthog@localhost:5432/cyclotron',

        CYCLOTRON_SHARD_DEPTH_LIMIT: 1000000,

        // New IngestionConsumer config
        INGESTION_CONSUMER_GROUP_ID: 'events-ingestion-consumer',
        INGESTION_CONSUMER_CONSUME_TOPIC: KAFKA_EVENTS_PLUGIN_INGESTION,
        INGESTION_CONSUMER_OVERFLOW_TOPIC: KAFKA_EVENTS_PLUGIN_INGESTION_OVERFLOW,
        INGESTION_CONSUMER_DLQ_TOPIC: KAFKA_EVENTS_PLUGIN_INGESTION_DLQ,
        INGESTION_JOINED_PIPELINE: false,

        // PropertyDefsConsumer config
        PROPERTY_DEFS_CONSUMER_GROUP_ID: 'property-defs-consumer',
        PROPERTY_DEFS_CONSUMER_CONSUME_TOPIC: KAFKA_EVENTS_JSON,
        PROPERTY_DEFS_CONSUMER_ENABLED_TEAMS: isDevEnv() ? '*' : '',
        PROPERTY_DEFS_WRITE_DISABLED: isProdEnv() ? true : false, // For now we don't want to do writes on prod - only count them

        // temporary: enable, rate limit expensive measurement in persons processing; value in [0,1]
        PERSON_JSONB_SIZE_ESTIMATE_ENABLE: 0, // defaults to off

        // Session recording V2
        SESSION_RECORDING_MAX_BATCH_SIZE_KB: isDevEnv() ? 2 * 1024 : 100 * 1024, // 2MB on dev, 100MB on prod and test
        SESSION_RECORDING_MAX_BATCH_AGE_MS: 10 * 1000, // 10 seconds
        SESSION_RECORDING_V2_S3_BUCKET: 'posthog',
        SESSION_RECORDING_V2_S3_PREFIX: 'session_recordings',
        SESSION_RECORDING_V2_S3_ENDPOINT: 'http://localhost:8333',
        SESSION_RECORDING_V2_S3_REGION: 'us-east-1',
        SESSION_RECORDING_V2_S3_ACCESS_KEY_ID: 'any',
        SESSION_RECORDING_V2_S3_SECRET_ACCESS_KEY: 'any',
        SESSION_RECORDING_V2_S3_TIMEOUT_MS: isDevEnv() ? 120000 : 30000,
        SESSION_RECORDING_V2_REPLAY_EVENTS_KAFKA_TOPIC: 'clickhouse_session_replay_events',
        SESSION_RECORDING_V2_CONSOLE_LOG_ENTRIES_KAFKA_TOPIC: 'log_entries',
        SESSION_RECORDING_V2_CONSOLE_LOG_STORE_SYNC_BATCH_LIMIT: 1000,
        SESSION_RECORDING_V2_MAX_EVENTS_PER_SESSION_PER_BATCH: Number.MAX_SAFE_INTEGER,

        // Cookieless
        COOKIELESS_FORCE_STATELESS_MODE: false,
        COOKIELESS_DISABLED: false,
        COOKIELESS_DELETE_EXPIRED_LOCAL_SALTS_INTERVAL_MS: 60 * 60 * 1000, // 1 hour
        COOKIELESS_SESSION_TTL_SECONDS: 60 * 60 * (72 + 24), // 96 hours (72 ingestion lag + 24 validity)
        COOKIELESS_SALT_TTL_SECONDS: 60 * 60 * (72 + 24), // 96 hours (72 ingestion lag + 24 validity)
        COOKIELESS_SESSION_INACTIVITY_MS: 30 * 60 * 1000, // 30 minutes
        COOKIELESS_IDENTIFIES_TTL_SECONDS:
            (72 + // max supported ingestion lag in hours
                12 + // max negative timezone in the world*/
                14 + // max positive timezone in the world */
                24) * // amount of time salt is valid in one timezone
            60 *
            60,
        COOKIELESS_REDIS_HOST: '',
        COOKIELESS_REDIS_PORT: 6379,

        // Timestamp comparison logging (0.0 = disabled, 1.0 = 100% sampling)
        TIMESTAMP_COMPARISON_LOGGING_SAMPLE_RATE: isDevEnv() || isTestEnv() ? 1.0 : 0.0,

        PERSON_BATCH_WRITING_DB_WRITE_MODE: 'NO_ASSERT',
        PERSON_BATCH_WRITING_OPTIMISTIC_UPDATES_ENABLED: false,
        PERSON_BATCH_WRITING_MAX_CONCURRENT_UPDATES: 10,
        PERSON_BATCH_WRITING_MAX_OPTIMISTIC_UPDATE_RETRIES: 5,
        PERSON_BATCH_WRITING_OPTIMISTIC_UPDATE_RETRY_INTERVAL_MS: 50,
        PERSON_UPDATE_CALCULATE_PROPERTIES_SIZE: 0,
        // DB constraint check uses pg_column_size(properties); default 512kb + 128kb = 655360 bytes
        PERSON_PROPERTIES_DB_CONSTRAINT_LIMIT_BYTES: 655360,
        // Trim target is the customer-facing limit (512kb)
        PERSON_PROPERTIES_TRIM_TARGET_BYTES: 512 * 1024,
        // When true, all property changes trigger person updates (disables filtering)
        PERSON_PROPERTIES_UPDATE_ALL: false,
        // Limit per merge for moving distinct IDs. 0 disables limiting (move all)
        PERSON_MERGE_MOVE_DISTINCT_ID_LIMIT: 0,
        // Topic for async person merge processing
        PERSON_MERGE_ASYNC_TOPIC: '',
        // Enable async person merge processing
        PERSON_MERGE_ASYNC_ENABLED: false,
        // Batch size for sync person merge processing (0 = unlimited, process all distinct IDs in one query)
        PERSON_MERGE_SYNC_BATCH_SIZE: 0,

        GROUP_BATCH_WRITING_MAX_CONCURRENT_UPDATES: 10,
        GROUP_BATCH_WRITING_OPTIMISTIC_UPDATE_RETRY_INTERVAL_MS: 50,
        GROUP_BATCH_WRITING_MAX_OPTIMISTIC_UPDATE_RETRIES: 5,
        PERSONS_PREFETCH_ENABLED: false,

        // SES (Workflows email sending)
        SES_ENDPOINT: isTestEnv() || isDevEnv() ? 'http://localhost:4566' : '',
        SES_ACCESS_KEY_ID: isTestEnv() || isDevEnv() ? 'test' : '',
        SES_SECRET_ACCESS_KEY: isTestEnv() || isDevEnv() ? 'test' : '',
        SES_REGION: isTestEnv() || isDevEnv() ? 'us-east-1' : '',

        // Pod termination
        POD_TERMINATION_ENABLED: false,
        POD_TERMINATION_BASE_TIMEOUT_MINUTES: 30, // Default: 30 minutes
        POD_TERMINATION_JITTER_MINUTES: 45, // Default: 45 hour, so timeout is between 30 minutes and 1h15m

        // Logs ingestion
        LOGS_INGESTION_CONSUMER_GROUP_ID: 'ingestion-logs',
        LOGS_INGESTION_CONSUMER_CONSUME_TOPIC: KAFKA_LOGS_INGESTION,
        LOGS_INGESTION_CONSUMER_OVERFLOW_TOPIC: KAFKA_LOGS_INGESTION_OVERFLOW,
        LOGS_INGESTION_CONSUMER_DLQ_TOPIC: KAFKA_LOGS_INGESTION_DLQ,
        LOGS_INGESTION_CONSUMER_CLICKHOUSE_TOPIC: KAFKA_LOGS_CLICKHOUSE,
        LOGS_REDIS_HOST: '127.0.0.1',
        LOGS_REDIS_PORT: 6479,
        LOGS_REDIS_PASSWORD: '',
        LOGS_REDIS_TLS: isProdEnv() ? true : false,
        LOGS_LIMITER_ENABLED_TEAMS: isProdEnv() ? '' : '*',
        LOGS_LIMITER_DISABLED_FOR_TEAMS: '',
        LOGS_LIMITER_BUCKET_SIZE_KB: 10000, // 10MB burst
        LOGS_LIMITER_REFILL_RATE_KB_PER_SECOND: 1000, // 1MB/second refill rate
        LOGS_LIMITER_TTL_SECONDS: 60 * 60 * 24,
        LOGS_LIMITER_TEAM_BUCKET_SIZE_KB: '',
        LOGS_LIMITER_TEAM_REFILL_RATE_KB_PER_SECOND: '',
    }
}

export function overrideWithEnv(
    config: PluginsServerConfig,
    env: Record<string, string | undefined> = process.env
): PluginsServerConfig {
    const defaultConfig = getDefaultConfig() as any // to make typechecker happy to use defaultConfig[key]

    const tmpConfig: any = { ...config }
    for (const key of Object.keys(config)) {
        if (typeof env[key] !== 'undefined') {
            if (key == 'PLUGIN_SERVER_MODE') {
                const mode = env[key]
                if (mode == null || mode in stringToPluginServerMode) {
                    tmpConfig[key] = env[key]
                } else {
                    throw Error(`Invalid PLUGIN_SERVER_MODE ${env[key]}`)
                }
            } else if (typeof defaultConfig[key] === 'number') {
                tmpConfig[key] = env[key]?.indexOf('.') ? parseFloat(env[key]!) : parseInt(env[key]!)
            } else if (typeof defaultConfig[key] === 'boolean') {
                tmpConfig[key] = stringToBoolean(env[key])
            } else {
                tmpConfig[key] = env[key]
            }
        }
    }
    const newConfig: PluginsServerConfig = { ...tmpConfig }

    if (!newConfig.DATABASE_URL && !newConfig.POSTHOG_DB_NAME) {
        throw Error(
            'You must specify either DATABASE_URL or the database options POSTHOG_DB_NAME, POSTHOG_DB_USER, POSTHOG_DB_PASSWORD, POSTHOG_POSTGRES_HOST, POSTHOG_POSTGRES_PORT!'
        )
    }

    if (!newConfig.DATABASE_URL) {
        const encodedUser = encodeURIComponent(newConfig.POSTHOG_DB_USER)
        const encodedPassword = encodeURIComponent(newConfig.POSTHOG_DB_PASSWORD)
        newConfig.DATABASE_URL = `postgres://${encodedUser}:${encodedPassword}@${newConfig.POSTHOG_POSTGRES_HOST}:${newConfig.POSTHOG_POSTGRES_PORT}/${newConfig.POSTHOG_DB_NAME}`
    }

    if (
        !newConfig.BEHAVIORAL_COHORTS_DATABASE_URL &&
        newConfig.POSTGRES_BEHAVIORAL_COHORTS_HOST &&
        newConfig.POSTGRES_BEHAVIORAL_COHORTS_USER &&
        newConfig.POSTGRES_BEHAVIORAL_COHORTS_PASSWORD
    ) {
        const encodedUser = encodeURIComponent(newConfig.POSTGRES_BEHAVIORAL_COHORTS_USER)
        const encodedPassword = encodeURIComponent(newConfig.POSTGRES_BEHAVIORAL_COHORTS_PASSWORD)
        newConfig.BEHAVIORAL_COHORTS_DATABASE_URL = `postgres://${encodedUser}:${encodedPassword}@${newConfig.POSTGRES_BEHAVIORAL_COHORTS_HOST}:5432/behavioral_cohorts`
    }

    return newConfig
}

export function buildIntegerMatcher(config: string | undefined, allowStar: boolean): ValueMatcher<number> {
    // Builds a ValueMatcher on a comma-separated list of values.
    // Optionally, supports a '*' value to match everything
    if (!config || config.trim().length == 0) {
        return () => false
    } else if (allowStar && config === '*') {
        return () => true
    } else {
        const values = new Set(
            config
                .split(',')
                .map((n) => parseInt(n))
                .filter((num) => !isNaN(num))
        )
        return (v: number) => {
            return values.has(v)
        }
    }
}

export function buildStringMatcher(config: string | undefined, allowStar: boolean): ValueMatcher<string> {
    // Builds a ValueMatcher on a comma-separated list of values.
    // Optionally, supports a '*' value to match everything
    if (!config || config.trim().length == 0) {
        return () => false
    } else if (allowStar && config === '*') {
        return () => true
    } else {
        const values = new Set(config.split(','))
        return (v: string) => {
            return values.has(v)
        }
    }
}
