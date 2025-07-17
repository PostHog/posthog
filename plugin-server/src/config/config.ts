import { LogLevel, PluginLogLevel, PluginsServerConfig, stringToPluginServerMode, ValueMatcher } from '../types'
import { isDevEnv, isProdEnv, isTestEnv, stringToBoolean } from '../utils/env-utils'
import { KAFKAJS_LOG_LEVEL_MAPPING } from './constants'
import {
    KAFKA_APP_METRICS_2,
    KAFKA_CLICKHOUSE_HEATMAP_EVENTS,
    KAFKA_EVENTS_JSON,
    KAFKA_EVENTS_PLUGIN_INGESTION,
    KAFKA_EVENTS_PLUGIN_INGESTION_DLQ,
    KAFKA_EVENTS_PLUGIN_INGESTION_OVERFLOW,
    KAFKA_EXCEPTION_SYMBOLIFICATION_EVENTS,
    KAFKA_LOG_ENTRIES,
} from './kafka-topics'

export const DEFAULT_HTTP_SERVER_PORT = 6738

export const defaultConfig = overrideWithEnv(getDefaultConfig())

export function getDefaultConfig(): PluginsServerConfig {
    return {
        INSTRUMENT_THREAD_PERFORMANCE: false,
        DATABASE_URL: isTestEnv()
            ? 'postgres://posthog:posthog@localhost:5432/test_posthog'
            : isDevEnv()
            ? 'postgres://posthog:posthog@localhost:5432/posthog'
            : '',
        DATABASE_READONLY_URL: '',
        PLUGIN_STORAGE_DATABASE_URL: '',
        PERSONS_DATABASE_URL: isTestEnv()
            ? 'postgres://posthog:posthog@localhost:5432/test_posthog'
            : isDevEnv()
            ? 'postgres://posthog:posthog@localhost:5432/posthog'
            : '',
        PERSONS_READONLY_DATABASE_URL: '',
        POSTGRES_CONNECTION_POOL_SIZE: 10,
        POSTHOG_DB_NAME: null,
        POSTHOG_DB_USER: 'postgres',
        POSTHOG_DB_PASSWORD: '',
        POSTHOG_POSTGRES_HOST: 'localhost',
        POSTHOG_POSTGRES_PORT: 5432,
        CLICKHOUSE_HOST: 'localhost',
        CLICKHOUSE_OFFLINE_CLUSTER_HOST: null,
        CLICKHOUSE_DATABASE: isTestEnv() ? 'posthog_test' : 'default',
        CLICKHOUSE_USER: 'default',
        CLICKHOUSE_PASSWORD: null,
        CLICKHOUSE_CA: null,
        CLICKHOUSE_SECURE: false,
        EVENT_OVERFLOW_BUCKET_CAPACITY: 1000,
        EVENT_OVERFLOW_BUCKET_REPLENISH_RATE: 1.0,
        KAFKA_BATCH_START_LOGGING_ENABLED: false,
        SKIP_UPDATE_EVENT_AND_PROPERTIES_STEP: false,
        CONSUMER_BATCH_SIZE: 500,
        CONSUMER_MAX_HEARTBEAT_INTERVAL_MS: 30_000,
        CONSUMER_MAX_BACKGROUND_TASKS: 1,
        CONSUMER_AUTO_CREATE_TOPICS: true,
        KAFKA_HOSTS: 'kafka:9092', // KEEP IN SYNC WITH posthog/settings/data_stores.py
        KAFKA_CLIENT_CERT_B64: undefined,
        KAFKA_CLIENT_CERT_KEY_B64: undefined,
        KAFKA_TRUSTED_CERT_B64: undefined,
        KAFKA_SECURITY_PROTOCOL: undefined,
        KAFKA_SASL_MECHANISM: undefined,
        KAFKA_SASL_USER: undefined,
        KAFKA_SASL_PASSWORD: undefined,
        KAFKA_CLIENT_RACK: undefined,
        KAFKA_CONSUMPTION_REBALANCE_TIMEOUT_MS: null,
        KAFKA_CONSUMPTION_SESSION_TIMEOUT_MS: 30_000,
        APP_METRICS_FLUSH_FREQUENCY_MS: isTestEnv() ? 5 : 20_000,
        APP_METRICS_FLUSH_MAX_QUEUE_SIZE: isTestEnv() ? 5 : 1000,
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
        PLUGINS_DEFAULT_LOG_LEVEL: isTestEnv() ? PluginLogLevel.Full : PluginLogLevel.Log,
        LOG_LEVEL: isTestEnv() ? LogLevel.Warn : LogLevel.Info,
        HTTP_SERVER_PORT: DEFAULT_HTTP_SERVER_PORT,
        SCHEDULE_LOCK_TTL: 60,
        REDIS_POOL_MIN_SIZE: 1,
        REDIS_POOL_MAX_SIZE: 3,
        MMDB_FILE_LOCATION: '../share/GeoLite2-City.mmdb',
        DISTINCT_ID_LRU_SIZE: 10000,
        EVENT_PROPERTY_LRU_SIZE: 10000,
        HEALTHCHECK_MAX_STALE_SECONDS: 2 * 60 * 60, // 2 hours
        SITE_URL: isDevEnv() ? 'http://localhost:8000' : '',
        KAFKA_PARTITIONS_CONSUMED_CONCURRENTLY: 1,
        CLICKHOUSE_JSON_EVENTS_KAFKA_TOPIC: KAFKA_EVENTS_JSON,
        CLICKHOUSE_HEATMAPS_KAFKA_TOPIC: KAFKA_CLICKHOUSE_HEATMAP_EVENTS,
        EXCEPTIONS_SYMBOLIFICATION_KAFKA_TOPIC: KAFKA_EXCEPTION_SYMBOLIFICATION_EVENTS,
        PERSON_INFO_CACHE_TTL: 5 * 60, // 5 min
        KAFKA_HEALTHCHECK_SECONDS: 20,
        OBJECT_STORAGE_ENABLED: true,
        OBJECT_STORAGE_ENDPOINT: 'http://localhost:19000',
        OBJECT_STORAGE_REGION: 'us-east-1',
        OBJECT_STORAGE_ACCESS_KEY_ID: 'object_storage_root_user',
        OBJECT_STORAGE_SECRET_ACCESS_KEY: 'object_storage_root_password',
        OBJECT_STORAGE_BUCKET: 'posthog',
        PLUGIN_SERVER_MODE: null,
        PLUGIN_SERVER_EVENTS_INGESTION_PIPELINE: null,
        PLUGIN_LOAD_SEQUENTIALLY: false,
        KAFKAJS_LOG_LEVEL: 'WARN',
        MAX_TEAM_ID_TO_BUFFER_ANONYMOUS_EVENTS_FOR: 0,
        CLOUD_DEPLOYMENT: null,
        EXTERNAL_REQUEST_TIMEOUT_MS: 10 * 1000, // 10 seconds
        DROP_EVENTS_BY_TOKEN_DISTINCT_ID: '',
        SKIP_PERSONS_PROCESSING_BY_TOKEN_DISTINCT_ID: '',
        PIPELINE_STEP_STALLED_LOG_TIMEOUT: 30,
        RELOAD_PLUGIN_JITTER_MAX_MS: 60000,
        RUSTY_HOOK_FOR_TEAMS: '',
        RUSTY_HOOK_ROLLOUT_PERCENTAGE: 0,
        RUSTY_HOOK_URL: '',
        HOG_HOOK_URL: '',
        CAPTURE_CONFIG_REDIS_HOST: null,
        LAZY_LOADER_DEFAULT_BUFFER_MS: 10,

        // posthog
        POSTHOG_API_KEY: '',
        POSTHOG_HOST_URL: 'http://localhost:8010',

        STARTUP_PROFILE_DURATION_SECONDS: 300, // 5 minutes
        STARTUP_PROFILE_CPU: false,
        STARTUP_PROFILE_HEAP: false,
        STARTUP_PROFILE_HEAP_INTERVAL: 512 * 1024, // default v8 value
        STARTUP_PROFILE_HEAP_DEPTH: 16, // default v8 value

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
        CDP_WATCHER_DISABLED_TEMPORARY_MAX_COUNT: 3,
        CDP_HOG_FILTERS_TELEMETRY_TEAMS: '',
        CDP_REDIS_PASSWORD: '',
        CDP_EVENT_PROCESSOR_EXECUTE_FIRST_STEP: true,
        CDP_REDIS_HOST: '',
        CDP_REDIS_PORT: 6479,
        CDP_CYCLOTRON_BATCH_DELAY_MS: 50,
        CDP_GOOGLE_ADWORDS_DEVELOPER_TOKEN: '',
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
        CDP_FETCH_TIMEOUT_MS: 10 * 1000, // 10 seconds
        CDP_FETCH_RETRIES: 3,
        CDP_FETCH_BACKOFF_BASE_MS: 1000,
        CDP_FETCH_BACKOFF_MAX_MS: 30000,

        CDP_LEGACY_EVENT_CONSUMER_GROUP_ID: 'clickhouse-plugin-server-async-onevent',
        CDP_LEGACY_EVENT_CONSUMER_TOPIC: KAFKA_EVENTS_JSON,
        CDP_LEGACY_EVENT_REDIRECT_TOPIC: '',

        CDP_PLUGIN_CAPTURE_EVENTS_TOPIC: KAFKA_EVENTS_PLUGIN_INGESTION,

        HOG_FUNCTION_MONITORING_APP_METRICS_TOPIC: KAFKA_APP_METRICS_2,
        HOG_FUNCTION_MONITORING_LOG_ENTRIES_TOPIC: KAFKA_LOG_ENTRIES,
        HOG_FUNCTION_MONITORING_EVENTS_PRODUCED_TOPIC: KAFKA_EVENTS_PLUGIN_INGESTION,

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
        INGESTION_CONSUMER_TESTING_TOPIC: '',

        // PropertyDefsConsumer config
        PROPERTY_DEFS_CONSUMER_GROUP_ID: 'property-defs-consumer',
        PROPERTY_DEFS_CONSUMER_CONSUME_TOPIC: KAFKA_EVENTS_JSON,
        PROPERTY_DEFS_CONSUMER_ENABLED_TEAMS: isDevEnv() ? '*' : '',
        PROPERTY_DEFS_WRITE_DISABLED: isProdEnv() ? true : false, // For now we don't want to do writes on prod - only count them

        // temporary: enable, rate limit expensive measurement in persons processing; value in [0,1]
        PERSON_JSONB_SIZE_ESTIMATE_ENABLE: 0, // defaults to off
        PERSON_PROPERTY_JSONB_UPDATE_OPTIMIZATION: 0.0, // defaults to off, value in [0,1] for percentage rollout

        // Session recording V2
        SESSION_RECORDING_MAX_BATCH_SIZE_KB: 100 * 1024, // 100MB
        SESSION_RECORDING_MAX_BATCH_AGE_MS: 10 * 1000, // 10 seconds
        SESSION_RECORDING_V2_S3_BUCKET: 'posthog',
        SESSION_RECORDING_V2_S3_PREFIX: 'session_recording_batches',
        SESSION_RECORDING_V2_S3_ENDPOINT: 'http://localhost:19000',
        SESSION_RECORDING_V2_S3_REGION: 'us-east-1',
        SESSION_RECORDING_V2_S3_ACCESS_KEY_ID: 'object_storage_root_user',
        SESSION_RECORDING_V2_S3_SECRET_ACCESS_KEY: 'object_storage_root_password',
        SESSION_RECORDING_V2_S3_TIMEOUT_MS: 30000,
        SESSION_RECORDING_V2_REPLAY_EVENTS_KAFKA_TOPIC: 'clickhouse_session_replay_events',
        SESSION_RECORDING_V2_CONSOLE_LOG_ENTRIES_KAFKA_TOPIC: 'log_entries',
        SESSION_RECORDING_V2_CONSOLE_LOG_STORE_SYNC_BATCH_LIMIT: 1000,
        SESSION_RECORDING_V2_METADATA_SWITCHOVER: '',

        // Cookieless
        COOKIELESS_FORCE_STATELESS_MODE: false,
        COOKIELESS_DISABLED: false,
        COOKIELESS_DELETE_EXPIRED_LOCAL_SALTS_INTERVAL_MS: 60 * 60 * 1000, // 1 hour
        COOKIELESS_SESSION_TTL_SECONDS: 60 * 60 * 24, // 24 hours
        COOKIELESS_SALT_TTL_SECONDS: 60 * 60 * 24, // 24 hours
        COOKIELESS_SESSION_INACTIVITY_MS: 30 * 60 * 1000, // 30 minutes
        COOKIELESS_IDENTIFIES_TTL_SECONDS:
            (24 + // max supported ingestion lag
                12 + // max negative timezone in the world*/
                14 + // max positive timezone in the world */
                24) * // amount of time salt is valid in one timezone
            60 *
            60,

        PERSON_BATCH_WRITING_DB_WRITE_MODE: 'NO_ASSERT',
        PERSON_BATCH_WRITING_MODE: 'NONE',
        PERSON_BATCH_WRITING_SHADOW_MODE_PERCENTAGE: 0,
        PERSON_BATCH_WRITING_OPTIMISTIC_UPDATES_ENABLED: false,
        PERSON_BATCH_WRITING_MAX_CONCURRENT_UPDATES: 10,
        PERSON_BATCH_WRITING_MAX_OPTIMISTIC_UPDATE_RETRIES: 5,
        PERSON_BATCH_WRITING_OPTIMISTIC_UPDATE_RETRY_INTERVAL_MS: 50,
        PERSON_CACHE_ENABLED_FOR_UPDATES: true,
        PERSON_CACHE_ENABLED_FOR_CHECKS: true,
        GROUP_BATCH_WRITING_ENABLED: false,
        GROUP_BATCH_WRITING_MAX_CONCURRENT_UPDATES: 10,
        GROUP_BATCH_WRITING_OPTIMISTIC_UPDATE_RETRY_INTERVAL_MS: 50,
        GROUP_BATCH_WRITING_MAX_OPTIMISTIC_UPDATE_RETRIES: 5,
        USE_DYNAMIC_EVENT_INGESTION_RESTRICTION_CONFIG: false,

        // Messaging
        MAILJET_PUBLIC_KEY: '',
        MAILJET_SECRET_KEY: '',
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

    if (!Object.keys(KAFKAJS_LOG_LEVEL_MAPPING).includes(newConfig.KAFKAJS_LOG_LEVEL)) {
        throw Error(
            `Invalid KAFKAJS_LOG_LEVEL ${newConfig.KAFKAJS_LOG_LEVEL}. Valid: ${Object.keys(
                KAFKAJS_LOG_LEVEL_MAPPING
            ).join(', ')}`
        )
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
