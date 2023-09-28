import { LogLevel, PluginsServerConfig, stringToPluginServerMode, ValueMatcher } from '../types'
import { isDevEnv, isTestEnv, stringToBoolean } from '../utils/env-utils'
import { KAFKAJS_LOG_LEVEL_MAPPING } from './constants'
import {
    KAFKA_EVENTS_JSON,
    KAFKA_EVENTS_PLUGIN_INGESTION,
    KAFKA_EVENTS_PLUGIN_INGESTION_OVERFLOW,
} from './kafka-topics'

export const DEFAULT_HTTP_SERVER_PORT = 6738

export const defaultConfig = overrideWithEnv(getDefaultConfig())

export function getDefaultConfig(): PluginsServerConfig {
    return {
        DATABASE_URL: isTestEnv()
            ? 'postgres://posthog:posthog@localhost:5432/test_posthog'
            : isDevEnv()
            ? 'postgres://posthog:posthog@localhost:5432/posthog'
            : '',
        DATABASE_READONLY_URL: '',
        PLUGIN_STORAGE_DATABASE_URL: '',
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
        CLICKHOUSE_DISABLE_EXTERNAL_SCHEMAS: true,
        EVENT_OVERFLOW_BUCKET_CAPACITY: 1000,
        EVENT_OVERFLOW_BUCKET_REPLENISH_RATE: 1.0,
        KAFKA_HOSTS: 'kafka:9092', // KEEP IN SYNC WITH posthog/settings/data_stores.py
        KAFKA_CLIENT_CERT_B64: undefined,
        KAFKA_CLIENT_CERT_KEY_B64: undefined,
        KAFKA_TRUSTED_CERT_B64: undefined,
        KAFKA_SECURITY_PROTOCOL: undefined,
        KAFKA_SASL_MECHANISM: undefined,
        KAFKA_SASL_USER: undefined,
        KAFKA_SASL_PASSWORD: undefined,
        KAFKA_CLIENT_RACK: undefined,
        KAFKA_CONSUMPTION_USE_RDKAFKA: false, // Transitional setting, ignored for consumers that only support one library
        KAFKA_CONSUMPTION_RDKAFKA_COOPERATIVE_REBALANCE: true, // If true, use the cooperative rebalance strategy, otherwise uses the default ('range,roundrobin')
        KAFKA_CONSUMPTION_MAX_BYTES: 10_485_760, // Default value for kafkajs
        KAFKA_CONSUMPTION_MAX_BYTES_PER_PARTITION: 1_048_576, // Default value for kafkajs, must be bigger than message size
        KAFKA_CONSUMPTION_MAX_WAIT_MS: 1_000, // Down from the 5s default for kafkajs
        KAFKA_CONSUMPTION_ERROR_BACKOFF_MS: 500, // Timeout when a partition read fails (possibly because empty)
        KAFKA_CONSUMPTION_BATCHING_TIMEOUT_MS: 500, // Timeout on reads from the prefetch buffer before running consumer loops
        KAFKA_CONSUMPTION_TOPIC: KAFKA_EVENTS_PLUGIN_INGESTION,
        KAFKA_CONSUMPTION_OVERFLOW_TOPIC: KAFKA_EVENTS_PLUGIN_INGESTION_OVERFLOW,
        KAFKA_CONSUMPTION_REBALANCE_TIMEOUT_MS: null,
        KAFKA_CONSUMPTION_SESSION_TIMEOUT_MS: 30_000,
        KAFKA_TOPIC_CREATION_TIMEOUT_MS: isDevEnv() ? 30_000 : 5_000, // rdkafka default is 5s, increased in devenv to resist to slow kafka
        KAFKA_PRODUCER_MAX_QUEUE_SIZE: isTestEnv() ? 0 : 1000,
        KAFKA_PRODUCER_WAIT_FOR_ACK: true, // Turning it off can lead to dropped data
        KAFKA_MAX_MESSAGE_BATCH_SIZE: isDevEnv() ? 0 : 900_000,
        KAFKA_FLUSH_FREQUENCY_MS: isTestEnv() ? 5 : 500,
        APP_METRICS_FLUSH_FREQUENCY_MS: isTestEnv() ? 5 : 20_000,
        APP_METRICS_FLUSH_MAX_QUEUE_SIZE: isTestEnv() ? 5 : 1000,
        REDIS_URL: 'redis://127.0.0.1',
        POSTHOG_REDIS_PASSWORD: '',
        POSTHOG_REDIS_HOST: '',
        POSTHOG_REDIS_PORT: 6379,
        BASE_DIR: '.',
        PLUGINS_RELOAD_PUBSUB_CHANNEL: 'reload-plugins',
        WORKER_CONCURRENCY: 1,
        TASK_TIMEOUT: 30,
        TASKS_PER_WORKER: 10,
        INGESTION_CONCURRENCY: 10,
        INGESTION_BATCH_SIZE: 500,
        LOG_LEVEL: isTestEnv() ? LogLevel.Warn : LogLevel.Info,
        SENTRY_DSN: null,
        SENTRY_PLUGIN_SERVER_TRACING_SAMPLE_RATE: 0,
        SENTRY_PLUGIN_SERVER_PROFILING_SAMPLE_RATE: 0,
        HTTP_SERVER_PORT: DEFAULT_HTTP_SERVER_PORT,
        STATSD_HOST: null,
        STATSD_PORT: 8125,
        STATSD_PREFIX: 'plugin-server.',
        SCHEDULE_LOCK_TTL: 60,
        REDIS_POOL_MIN_SIZE: 1,
        REDIS_POOL_MAX_SIZE: 3,
        DISABLE_MMDB: isTestEnv(),
        DISTINCT_ID_LRU_SIZE: 10000,
        EVENT_PROPERTY_LRU_SIZE: 10000,
        JOB_QUEUES: 'graphile',
        JOB_QUEUE_GRAPHILE_URL: '',
        JOB_QUEUE_GRAPHILE_SCHEMA: 'graphile_worker',
        JOB_QUEUE_GRAPHILE_PREPARED_STATEMENTS: false,
        JOB_QUEUE_GRAPHILE_CONCURRENCY: 1,
        JOB_QUEUE_S3_AWS_ACCESS_KEY: '',
        JOB_QUEUE_S3_AWS_SECRET_ACCESS_KEY: '',
        JOB_QUEUE_S3_AWS_REGION: 'us-west-1',
        JOB_QUEUE_S3_BUCKET_NAME: '',
        JOB_QUEUE_S3_PREFIX: '',
        CRASH_IF_NO_PERSISTENT_JOB_QUEUE: false,
        HEALTHCHECK_MAX_STALE_SECONDS: 2 * 60 * 60, // 2 hours
        PISCINA_USE_ATOMICS: true,
        PISCINA_ATOMICS_TIMEOUT: 5000,
        SITE_URL: null,
        MAX_PENDING_PROMISES_PER_WORKER: 100,
        KAFKA_PARTITIONS_CONSUMED_CONCURRENTLY: 1,
        RECORDING_PARTITIONS_CONSUMED_CONCURRENTLY: 5,
        CLICKHOUSE_DISABLE_EXTERNAL_SCHEMAS_TEAMS: '',
        CLICKHOUSE_JSON_EVENTS_KAFKA_TOPIC: KAFKA_EVENTS_JSON,
        CONVERSION_BUFFER_ENABLED: false,
        CONVERSION_BUFFER_ENABLED_TEAMS: '',
        CONVERSION_BUFFER_TOPIC_ENABLED_TEAMS: '',
        BUFFER_CONVERSION_SECONDS: isDevEnv() ? 2 : 60, // KEEP IN SYNC WITH posthog/settings/ingestion.py
        FETCH_HOSTNAME_GUARD_TEAMS: '',
        PERSON_INFO_CACHE_TTL: 5 * 60, // 5 min
        KAFKA_HEALTHCHECK_SECONDS: 20,
        OBJECT_STORAGE_ENABLED: true,
        OBJECT_STORAGE_ENDPOINT: 'http://localhost:19000',
        OBJECT_STORAGE_REGION: 'us-east-1',
        OBJECT_STORAGE_ACCESS_KEY_ID: 'object_storage_root_user',
        OBJECT_STORAGE_SECRET_ACCESS_KEY: 'object_storage_root_password',
        OBJECT_STORAGE_BUCKET: 'posthog',
        PLUGIN_SERVER_MODE: null,
        PLUGIN_LOAD_SEQUENTIALLY: false,
        KAFKAJS_LOG_LEVEL: 'WARN',
        HISTORICAL_EXPORTS_ENABLED: true,
        HISTORICAL_EXPORTS_MAX_RETRY_COUNT: 15,
        HISTORICAL_EXPORTS_INITIAL_FETCH_TIME_WINDOW: 10 * 60 * 1000,
        HISTORICAL_EXPORTS_FETCH_WINDOW_MULTIPLIER: 1.5,
        APP_METRICS_GATHERED_FOR_ALL: isDevEnv() ? true : false,
        MAX_TEAM_ID_TO_BUFFER_ANONYMOUS_EVENTS_FOR: 0,
        USE_KAFKA_FOR_SCHEDULED_TASKS: true,
        CLOUD_DEPLOYMENT: null,

        STARTUP_PROFILE_DURATION_SECONDS: 300, // 5 minutes
        STARTUP_PROFILE_CPU: false,
        STARTUP_PROFILE_HEAP: false,
        STARTUP_PROFILE_HEAP_INTERVAL: 512 * 1024, // default v8 value
        STARTUP_PROFILE_HEAP_DEPTH: 16, // default v8 value

        SESSION_RECORDING_KAFKA_HOSTS: undefined,
        SESSION_RECORDING_KAFKA_SECURITY_PROTOCOL: undefined,
        SESSION_RECORDING_KAFKA_BATCH_SIZE: 500,
        SESSION_RECORDING_KAFKA_QUEUE_SIZE: 1500,

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
    }
}

export const sessionRecordingConsumerConfig = (config: PluginsServerConfig): PluginsServerConfig => {
    // When running the blob consumer we override a bunch of settings to use the session recording ones if available
    return {
        ...config,
        KAFKA_HOSTS: config.SESSION_RECORDING_KAFKA_HOSTS || config.KAFKA_HOSTS,
        KAFKA_SECURITY_PROTOCOL: config.SESSION_RECORDING_KAFKA_SECURITY_PROTOCOL || config.KAFKA_SECURITY_PROTOCOL,
        POSTHOG_REDIS_HOST: config.POSTHOG_SESSION_RECORDING_REDIS_HOST || config.POSTHOG_REDIS_HOST,
        POSTHOG_REDIS_PORT: config.POSTHOG_SESSION_RECORDING_REDIS_PORT || config.POSTHOG_REDIS_PORT,
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

    if (!newConfig.JOB_QUEUE_GRAPHILE_URL) {
        newConfig.JOB_QUEUE_GRAPHILE_URL = newConfig.DATABASE_URL
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
    // Builds a ValueMatcher on a coma-separated list of values.
    // Optionally, supports a '*' value to match everything
    if (!config) {
        return () => false
    } else if (allowStar && config === '*') {
        return () => true
    } else {
        const values = new Set(config.split(',').map((n) => parseInt(n)))
        return (v: number) => {
            return values.has(v)
        }
    }
}
