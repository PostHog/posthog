import os from 'os'

import { LogLevel, PluginsServerConfig } from '../types'
import { determineNodeEnv, NodeEnv, stringToBoolean } from '../utils/utils'
import { KAFKA_EVENTS_PLUGIN_INGESTION } from './kafka-topics'

export const defaultConfig = overrideWithEnv(getDefaultConfig())
export const configHelp = getConfigHelp()

export function getDefaultConfig(): PluginsServerConfig {
    const isTestEnv = determineNodeEnv() === NodeEnv.Test
    const isDevEnv = determineNodeEnv() === NodeEnv.Development
    const coreCount = os.cpus().length

    return {
        CELERY_DEFAULT_QUEUE: 'celery',
        DATABASE_URL: isTestEnv
            ? 'postgres://localhost:5432/test_posthog'
            : isDevEnv
            ? 'postgres://localhost:5432/posthog'
            : null,
        POSTHOG_DB_NAME: null,
        POSTHOG_DB_USER: 'postgres',
        POSTHOG_DB_PASSWORD: '',
        POSTHOG_POSTGRES_HOST: 'localhost',
        POSTHOG_POSTGRES_PORT: 5432,
        CLICKHOUSE_HOST: 'localhost',
        CLICKHOUSE_DATABASE: isTestEnv ? 'posthog_test' : 'default',
        CLICKHOUSE_USER: 'default',
        CLICKHOUSE_PASSWORD: null,
        CLICKHOUSE_CA: null,
        CLICKHOUSE_SECURE: false,
        KAFKA_ENABLED: false,
        KAFKA_HOSTS: null,
        KAFKA_CLIENT_CERT_B64: null,
        KAFKA_CLIENT_CERT_KEY_B64: null,
        KAFKA_TRUSTED_CERT_B64: null,
        KAFKA_CONSUMPTION_TOPIC: KAFKA_EVENTS_PLUGIN_INGESTION,
        KAFKA_PRODUCER_MAX_QUEUE_SIZE: isTestEnv ? 0 : 1000,
        KAFKA_MAX_MESSAGE_BATCH_SIZE: 900_000,
        KAFKA_FLUSH_FREQUENCY_MS: 500,
        PLUGINS_CELERY_QUEUE: 'posthog-plugins',
        REDIS_URL: 'redis://127.0.0.1',
        POSTHOG_REDIS_PASSWORD: '',
        POSTHOG_REDIS_HOST: '',
        POSTHOG_REDIS_PORT: 6379,
        BASE_DIR: '.',
        PLUGINS_RELOAD_PUBSUB_CHANNEL: 'reload-plugins',
        WORKER_CONCURRENCY: coreCount,
        TASK_TIMEOUT: 30,
        TASKS_PER_WORKER: 10,
        LOG_LEVEL: isTestEnv ? LogLevel.Warn : LogLevel.Info,
        SENTRY_DSN: null,
        STATSD_HOST: null,
        STATSD_PORT: 8125,
        STATSD_PREFIX: 'plugin-server.',
        SCHEDULE_LOCK_TTL: 60,
        REDIS_POOL_MIN_SIZE: 1,
        REDIS_POOL_MAX_SIZE: 3,
        DISABLE_MMDB: isTestEnv,
        DISTINCT_ID_LRU_SIZE: 10000,
        INTERNAL_MMDB_SERVER_PORT: 0,
        PLUGIN_SERVER_IDLE: false,
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
        CAPTURE_INTERNAL_METRICS: false,
        PISCINA_USE_ATOMICS: true,
        PISCINA_ATOMICS_TIMEOUT: 5000,
    }
}

export function getConfigHelp(): Record<keyof PluginsServerConfig, string> {
    return {
        CELERY_DEFAULT_QUEUE: 'Celery outgoing queue',
        PLUGINS_CELERY_QUEUE: 'Celery incoming queue',
        DATABASE_URL: 'Postgres database URL',
        CLICKHOUSE_HOST: 'ClickHouse host',
        CLICKHOUSE_DATABASE: 'ClickHouse database',
        CLICKHOUSE_USER: 'ClickHouse username',
        CLICKHOUSE_PASSWORD: 'ClickHouse password',
        CLICKHOUSE_CA: 'ClickHouse CA certs',
        CLICKHOUSE_SECURE: 'whether to secure ClickHouse connection',
        REDIS_URL: 'Redis store URL',
        BASE_DIR: 'base path for resolving local plugins',
        PLUGINS_RELOAD_PUBSUB_CHANNEL: 'Redis channel for reload events',
        WORKER_CONCURRENCY: 'number of concurrent worker threads',
        TASK_TIMEOUT: 'how many seconds until tasks are timed out',
        TASKS_PER_WORKER: 'number of parallel tasks per worker thread',
        LOG_LEVEL: 'minimum log level',
        KAFKA_ENABLED: 'use Kafka instead of Celery to ingest events',
        KAFKA_HOSTS: 'comma-delimited Kafka hosts',
        KAFKA_CONSUMPTION_TOPIC: 'Kafka consumption topic override',
        KAFKA_CLIENT_CERT_B64: 'Kafka certificate in Base64',
        KAFKA_CLIENT_CERT_KEY_B64: 'Kafka certificate key in Base64',
        KAFKA_TRUSTED_CERT_B64: 'Kafka trusted CA in Base64',
        SENTRY_DSN: 'Sentry ingestion URL',
        STATSD_HOST: 'StatsD host - integration disabled if this is not provided',
        STATSD_PORT: 'StatsD port',
        STATSD_PREFIX: 'StatsD prefix',
        SCHEDULE_LOCK_TTL: 'how many seconds to hold the lock for the schedule',
        REDIS_POOL_MIN_SIZE: 'minimum number of Redis connections to use per thread',
        REDIS_POOL_MAX_SIZE: 'maximum number of Redis connections to use per thread',
        DISABLE_MMDB: 'whether to disable fetching MaxMind database for IP location',
        DISTINCT_ID_LRU_SIZE: 'size of persons distinct ID LRU cache',
        INTERNAL_MMDB_SERVER_PORT: 'port of the internal server used for IP location (0 means random)',
        PLUGIN_SERVER_IDLE: 'whether to disengage the plugin server, e.g. for development',
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
        CAPTURE_INTERNAL_METRICS: 'capture internal metrics for posthog in posthog',
        PISCINA_USE_ATOMICS:
            'corresponds to the piscina useAtomics config option (https://github.com/piscinajs/piscina#constructor-new-piscinaoptions)',
        PISCINA_ATOMICS_TIMEOUT:
            '(advanced) corresponds to the length of time a piscina worker should block for when looking for tasks',
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
    return newConfig
}
