import os from 'os'

import { LogLevel, PluginsServerConfig } from '../types'
import { isDevEnv, isTestEnv, stringToBoolean } from '../utils/env-utils'
import { KAFKA_EVENTS_JSON, KAFKA_EVENTS_PLUGIN_INGESTION } from './kafka-topics'

export const defaultConfig = overrideWithEnv(getDefaultConfig())
export const configHelp = getConfigHelp()

export function getDefaultConfig(): PluginsServerConfig {
    const coreCount = os.cpus().length

    return {
        DATABASE_URL: isTestEnv()
            ? 'postgres://posthog:posthog@localhost:5432/test_posthog'
            : isDevEnv()
            ? 'postgres://posthog:posthog@localhost:5432/posthog'
            : null,
        POSTHOG_DB_NAME: null,
        POSTHOG_DB_USER: 'postgres',
        POSTHOG_DB_PASSWORD: '',
        POSTHOG_POSTGRES_HOST: 'localhost',
        POSTHOG_POSTGRES_PORT: 5432,
        CLICKHOUSE_HOST: 'localhost',
        CLICKHOUSE_DATABASE: isTestEnv() ? 'posthog_test' : 'default',
        CLICKHOUSE_USER: 'default',
        CLICKHOUSE_PASSWORD: null,
        CLICKHOUSE_CA: null,
        CLICKHOUSE_SECURE: false,
        CLICKHOUSE_DISABLE_EXTERNAL_SCHEMAS: true,
        KAFKA_HOSTS: 'kafka:9092', // KEEP IN SYNC WITH posthog/settings/data_stores.py
        KAFKA_CLIENT_CERT_B64: null,
        KAFKA_CLIENT_CERT_KEY_B64: null,
        KAFKA_TRUSTED_CERT_B64: null,
        KAFKA_SECURITY_PROTOCOL: null,
        KAFKA_SASL_MECHANISM: null,
        KAFKA_SASL_USER: null,
        KAFKA_SASL_PASSWORD: null,
        KAFKA_CONSUMPTION_TOPIC: KAFKA_EVENTS_PLUGIN_INGESTION,
        KAFKA_PRODUCER_MAX_QUEUE_SIZE: isTestEnv() ? 0 : 1000,
        KAFKA_MAX_MESSAGE_BATCH_SIZE: 900_000,
        KAFKA_FLUSH_FREQUENCY_MS: isTestEnv() ? 5 : 500,
        REDIS_URL: 'redis://127.0.0.1',
        POSTHOG_REDIS_PASSWORD: '',
        POSTHOG_REDIS_HOST: '',
        POSTHOG_REDIS_PORT: 6379,
        BASE_DIR: '.',
        PLUGINS_RELOAD_PUBSUB_CHANNEL: 'reload-plugins',
        WORKER_CONCURRENCY: coreCount,
        TASK_TIMEOUT: 30,
        TASKS_PER_WORKER: 10,
        LOG_LEVEL: isTestEnv() ? LogLevel.Warn : LogLevel.Info,
        SENTRY_DSN: null,
        STATSD_HOST: null,
        STATSD_PORT: 8125,
        STATSD_PREFIX: 'plugin-server.',
        SCHEDULE_LOCK_TTL: 60,
        REDIS_POOL_MIN_SIZE: 1,
        REDIS_POOL_MAX_SIZE: 3,
        DISABLE_MMDB: isTestEnv(),
        DISTINCT_ID_LRU_SIZE: 10000,
        EVENT_PROPERTY_LRU_SIZE: 10000,
        INTERNAL_MMDB_SERVER_PORT: 0,
        JOB_QUEUES: 'graphile',
        JOB_QUEUE_GRAPHILE_URL: '',
        JOB_QUEUE_GRAPHILE_SCHEMA: 'graphile_worker',
        JOB_QUEUE_GRAPHILE_PREPARED_STATEMENTS: false,
        JOB_QUEUE_S3_AWS_ACCESS_KEY: '',
        JOB_QUEUE_S3_AWS_SECRET_ACCESS_KEY: '',
        JOB_QUEUE_S3_AWS_REGION: 'us-west-1',
        JOB_QUEUE_S3_BUCKET_NAME: '',
        JOB_QUEUE_S3_PREFIX: '',
        CRASH_IF_NO_PERSISTENT_JOB_QUEUE: false,
        STALENESS_RESTART_SECONDS: 0,
        HEALTHCHECK_MAX_STALE_SECONDS: 2 * 60 * 60, // 2 hours
        CAPTURE_INTERNAL_METRICS: false,
        PISCINA_USE_ATOMICS: true,
        PISCINA_ATOMICS_TIMEOUT: 5000,
        SITE_URL: null,
        EXPERIMENTAL_EVENTS_LAST_SEEN_ENABLED: true,
        EXPERIMENTAL_EVENT_PROPERTY_TRACKER_ENABLED: true,
        MAX_PENDING_PROMISES_PER_WORKER: 100,
        KAFKA_PARTITIONS_CONSUMED_CONCURRENTLY: 1,
        CLICKHOUSE_DISABLE_EXTERNAL_SCHEMAS_TEAMS: '',
        CLICKHOUSE_JSON_EVENTS_KAFKA_TOPIC: KAFKA_EVENTS_JSON,
        CONVERSION_BUFFER_ENABLED: false,
        CONVERSION_BUFFER_ENABLED_TEAMS: '',
        BUFFER_CONVERSION_SECONDS: 60,
        PERSON_INFO_TO_REDIS_TEAMS: '',
        PERSON_INFO_CACHE_TTL: 5 * 60, // 5 min
        KAFKA_HEALTHCHECK_SECONDS: 20,
        HISTORICAL_EXPORTS_ENABLED: true,
        OBJECT_STORAGE_ENABLED: false,
        OBJECT_STORAGE_ENDPOINT: 'http://localhost:19000',
        OBJECT_STORAGE_ACCESS_KEY_ID: 'object_storage_root_user',
        OBJECT_STORAGE_SECRET_ACCESS_KEY: 'object_storage_root_password',
        OBJECT_STORAGE_SESSION_RECORDING_FOLDER: 'session_recordings',
        OBJECT_STORAGE_BUCKET: 'posthog',
        PLUGIN_SERVER_MODE: null,
        INGESTION_BATCH_BREAKUP_BY_DISTINCT_ID_TEAMS: '',
    }
}

export function getConfigHelp(): Record<keyof PluginsServerConfig, string> {
    return {
        DATABASE_URL: 'Postgres database URL',
        CLICKHOUSE_HOST: 'ClickHouse host',
        CLICKHOUSE_DATABASE: 'ClickHouse database',
        CLICKHOUSE_USER: 'ClickHouse username',
        CLICKHOUSE_PASSWORD: 'ClickHouse password',
        CLICKHOUSE_CA: 'ClickHouse CA certs',
        CLICKHOUSE_SECURE: 'whether to secure ClickHouse connection',
        CLICKHOUSE_DISABLE_EXTERNAL_SCHEMAS:
            'whether to disallow external schemas like protobuf for clickhouse kafka engine',
        REDIS_URL: 'Redis store URL',
        BASE_DIR: 'base path for resolving local plugins',
        PLUGINS_RELOAD_PUBSUB_CHANNEL: 'Redis channel for reload events',
        WORKER_CONCURRENCY: 'number of concurrent worker threads',
        TASK_TIMEOUT: 'how many seconds until tasks are timed out',
        TASKS_PER_WORKER: 'number of parallel tasks per worker thread',
        LOG_LEVEL: 'minimum log level',
        KAFKA_HOSTS: 'comma-delimited Kafka hosts',
        KAFKA_CONSUMPTION_TOPIC: 'Kafka consumption topic override',
        KAFKA_CLIENT_CERT_B64: 'Kafka certificate in Base64',
        KAFKA_CLIENT_CERT_KEY_B64: 'Kafka certificate key in Base64',
        KAFKA_TRUSTED_CERT_B64: 'Kafka trusted CA in Base64',
        KAFKA_SECURITY_PROTOCOL: 'Kafka security protocol, one of "PLAINTEXT", "SSL", "SASL_PLAINTEXT", or "SASL_SSL"',
        KAFKA_SASL_MECHANISM: 'Kafka SASL mechanism, one of "plain", "scram-sha-256", or "scram-sha-512"',
        KAFKA_SASL_USER: 'Kafka SASL username',
        KAFKA_SASL_PASSWORD: 'Kafka SASL password',
        SENTRY_DSN: 'Sentry ingestion URL',
        STATSD_HOST: 'StatsD host - integration disabled if this is not provided',
        STATSD_PORT: 'StatsD port',
        STATSD_PREFIX: 'StatsD prefix',
        SCHEDULE_LOCK_TTL: 'how many seconds to hold the lock for the schedule',
        REDIS_POOL_MIN_SIZE: 'minimum number of Redis connections to use per thread',
        REDIS_POOL_MAX_SIZE: 'maximum number of Redis connections to use per thread',
        DISABLE_MMDB: 'whether to disable fetching MaxMind database for IP location',
        DISTINCT_ID_LRU_SIZE: 'size of persons distinct ID LRU cache',
        EVENT_PROPERTY_LRU_SIZE: "size of the event property tracker's LRU cache (keyed by [team.id, event])",
        INTERNAL_MMDB_SERVER_PORT: 'port of the internal server used for IP location (0 means random)',
        JOB_QUEUES: 'retry queue engine and fallback queues',
        JOB_QUEUE_GRAPHILE_URL: 'use a different postgres connection in the graphile retry queue',
        JOB_QUEUE_GRAPHILE_SCHEMA: 'the postgres schema that the graphile job queue uses',
        JOB_QUEUE_GRAPHILE_PREPARED_STATEMENTS: 'enable this to increase job queue throughput if not using pgbouncer',
        JOB_QUEUE_S3_AWS_ACCESS_KEY: 'AWS access key for the S3 job queue',
        JOB_QUEUE_S3_AWS_SECRET_ACCESS_KEY: 'AWS secret access key for the S3 job queue',
        JOB_QUEUE_S3_AWS_REGION: 'AWS region for the S3 job queue',
        JOB_QUEUE_S3_BUCKET_NAME: 'S3 bucket name for the S3 job queue',
        JOB_QUEUE_S3_PREFIX: 'S3 filename prefix for the S3 job queue',
        CRASH_IF_NO_PERSISTENT_JOB_QUEUE:
            'refuse to start unless there is a properly configured persistent job queue (e.g. graphile)',
        STALENESS_RESTART_SECONDS: 'trigger a restart if no event ingested for this duration',
        HEALTHCHECK_MAX_STALE_SECONDS:
            'maximum number of seconds the plugin server can go without ingesting events before the healthcheck fails',
        CAPTURE_INTERNAL_METRICS: 'capture internal metrics for posthog in posthog',
        PISCINA_USE_ATOMICS:
            'corresponds to the piscina useAtomics config option (https://github.com/piscinajs/piscina#constructor-new-piscinaoptions)',
        PISCINA_ATOMICS_TIMEOUT:
            '(advanced) corresponds to the length of time a piscina worker should block for when looking for tasks',
        NEW_PERSON_PROPERTIES_UPDATE_ENABLED_TEAMS:
            '(advanced) teams for which to run the new person properties update flow on',
        EXPERIMENTAL_EVENTS_LAST_SEEN_ENABLED: '(advanced) enable experimental feature to track lastSeenAt',
        EXPERIMENTAL_EVENT_PROPERTY_TRACKER_ENABLED: '(advanced) enable experimental feature to track event properties',
        MAX_PENDING_PROMISES_PER_WORKER:
            '(advanced) maximum number of promises that a worker can have running at once in the background. currently only targets the exportEvents buffer.',
        KAFKA_PARTITIONS_CONSUMED_CONCURRENTLY:
            '(advanced) how many kafka partitions the plugin server should consume from concurrently',
        CLICKHOUSE_DISABLE_EXTERNAL_SCHEMAS_TEAMS:
            '(advanced) a comma separated list of teams to disable clickhouse external schemas for',
        CLICKHOUSE_JSON_EVENTS_KAFKA_TOPIC: '(advanced) topic to send events to for clickhouse ingestion',
        PLUGIN_SERVER_MODE: '(advanced) plugin server mode',
        OBJECT_STORAGE_ENABLED:
            'Disables or enables the use of object storage. It will become mandatory to use object storage',
        OBJECT_STORAGE_ENDPOINT: 'minio endpoint',
        OBJECT_STORAGE_ACCESS_KEY_ID: 'access key for minio',
        OBJECT_STORAGE_SECRET_ACCESS_KEY: 'secret key for minio',
        OBJECT_STORAGE_SESSION_RECORDING_FOLDER:
            'the top level folder for storing session recordings inside the storage bucket',
        OBJECT_STORAGE_BUCKET: 'the object storage bucket name',
    }
}

export function formatConfigHelp(indentation = 0): string {
    const spaces = Array(indentation).fill(' ').join('')
    return Object.entries(getConfigHelp())
        .map(([variable, description]) => `${spaces}- ${variable} - ${description}`)
        .join('\n')
}

export function overrideWithEnv(
    config: PluginsServerConfig,
    env: Record<string, string | undefined> = process.env
): PluginsServerConfig {
    const defaultConfig = getDefaultConfig()

    const newConfig: PluginsServerConfig = { ...config }
    for (const key of Object.keys(config)) {
        if (typeof env[key] !== 'undefined') {
            if (typeof defaultConfig[key] === 'number') {
                newConfig[key] = env[key]?.indexOf('.') ? parseFloat(env[key]!) : parseInt(env[key]!)
            } else if (typeof defaultConfig[key] === 'boolean') {
                newConfig[key] = stringToBoolean(env[key])
            } else {
                newConfig[key] = env[key]
            }
        }
    }

    if (!['ingestion', 'async', null].includes(newConfig.PLUGIN_SERVER_MODE)) {
        throw Error(`Invalid PLUGIN_SERVER_MODE ${newConfig.PLUGIN_SERVER_MODE}`)
    }
    return newConfig
}
