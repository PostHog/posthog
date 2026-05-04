import {
    KAFKA_APP_METRICS_2,
    KAFKA_LOGS_CLICKHOUSE,
    KAFKA_LOGS_INGESTION,
    KAFKA_LOGS_INGESTION_DLQ,
    KAFKA_LOGS_INGESTION_OVERFLOW,
    KAFKA_TRACES_CLICKHOUSE,
    KAFKA_TRACES_INGESTION,
    KAFKA_TRACES_INGESTION_DLQ,
    KAFKA_TRACES_INGESTION_OVERFLOW,
} from '../config/kafka-topics'
import { isProdEnv } from '../utils/env-utils'
import { LogsProducerName, WARPSTREAM_INGESTION_PRODUCER, WARPSTREAM_LOGS_PRODUCER } from './outputs/producers'

export type LogsIngestionOutputsConfig = {
    LOGS_INGESTION_OUTPUT_APP_METRICS_TOPIC: string
    LOGS_INGESTION_OUTPUT_APP_METRICS_PRODUCER: LogsProducerName
    LOGS_INGESTION_OUTPUT_LOGS_PRODUCER: LogsProducerName
    LOGS_INGESTION_OUTPUT_DLQ_PRODUCER: LogsProducerName
}

export function getDefaultLogsIngestionOutputsConfig(): LogsIngestionOutputsConfig {
    return {
        LOGS_INGESTION_OUTPUT_APP_METRICS_TOPIC: KAFKA_APP_METRICS_2,
        LOGS_INGESTION_OUTPUT_APP_METRICS_PRODUCER: WARPSTREAM_INGESTION_PRODUCER,
        LOGS_INGESTION_OUTPUT_LOGS_PRODUCER: WARPSTREAM_LOGS_PRODUCER,
        LOGS_INGESTION_OUTPUT_DLQ_PRODUCER: WARPSTREAM_LOGS_PRODUCER,
    }
}

export type LogsIngestionConsumerConfig = {
    LOGS_INGESTION_CONSUMER_GROUP_ID: string
    LOGS_INGESTION_CONSUMER_CONSUME_TOPIC: string
    LOGS_INGESTION_CONSUMER_OVERFLOW_TOPIC: string
    LOGS_INGESTION_CONSUMER_DLQ_TOPIC: string
    LOGS_INGESTION_CONSUMER_CLICKHOUSE_TOPIC: string
    LOGS_REDIS_HOST: string
    LOGS_REDIS_PORT: number
    LOGS_REDIS_PASSWORD: string
    LOGS_REDIS_TLS: boolean
    LOGS_LIMITER_ENABLED_TEAMS: string
    LOGS_LIMITER_DISABLED_FOR_TEAMS: string
    LOGS_LIMITER_BUCKET_SIZE_KB: number
    LOGS_LIMITER_REFILL_RATE_KB_PER_SECOND: number
    LOGS_LIMITER_TTL_SECONDS: number
    LOGS_LIMITER_TEAM_BUCKET_SIZE_KB: string
    LOGS_LIMITER_TEAM_REFILL_RATE_KB_PER_SECOND: string
    /** Comma-separated team IDs, or `*` for all teams, or empty to disable sampling evaluation entirely. Default `*`; set empty in env to turn off globally. */
    LOGS_SAMPLING_ENABLED_TEAMS: string
    /** When `true`, sampling always keeps every record (metrics path may still run). */
    LOGS_SAMPLING_KILLSWITCH: boolean
    REDIS_URL: string
    REDIS_POOL_MIN_SIZE: number
    REDIS_POOL_MAX_SIZE: number
    KAFKA_CLIENT_RACK: string | undefined
}

export function getDefaultLogsIngestionConsumerConfig(): LogsIngestionConsumerConfig {
    return {
        LOGS_INGESTION_CONSUMER_GROUP_ID: 'ingestion-logs',
        LOGS_INGESTION_CONSUMER_CONSUME_TOPIC: KAFKA_LOGS_INGESTION,
        LOGS_INGESTION_CONSUMER_OVERFLOW_TOPIC: KAFKA_LOGS_INGESTION_OVERFLOW,
        LOGS_INGESTION_CONSUMER_DLQ_TOPIC: KAFKA_LOGS_INGESTION_DLQ,
        LOGS_INGESTION_CONSUMER_CLICKHOUSE_TOPIC: KAFKA_LOGS_CLICKHOUSE,
        LOGS_REDIS_HOST: '127.0.0.1',
        LOGS_REDIS_PORT: 6379,
        LOGS_REDIS_PASSWORD: '',
        LOGS_REDIS_TLS: isProdEnv() ? true : false,
        LOGS_LIMITER_ENABLED_TEAMS: isProdEnv() ? '' : '*',
        LOGS_LIMITER_DISABLED_FOR_TEAMS: '',
        LOGS_LIMITER_BUCKET_SIZE_KB: 10000,
        LOGS_LIMITER_REFILL_RATE_KB_PER_SECOND: 1000,
        LOGS_LIMITER_TTL_SECONDS: 60 * 60 * 24,
        LOGS_LIMITER_TEAM_BUCKET_SIZE_KB: '',
        LOGS_LIMITER_TEAM_REFILL_RATE_KB_PER_SECOND: '',
        LOGS_SAMPLING_ENABLED_TEAMS: '*',
        LOGS_SAMPLING_KILLSWITCH: false,
        // Overlapping fields with CommonConfig, included for standalone usage
        // ok to connect to localhost over plaintext
        // nosemgrep: trailofbits.generic.redis-unencrypted-transport.redis-unencrypted-transport
        REDIS_URL: 'redis://127.0.0.1',
        REDIS_POOL_MIN_SIZE: 1,
        REDIS_POOL_MAX_SIZE: 3,
        KAFKA_CLIENT_RACK: undefined,
    }
}

export type TracesIngestionConsumerConfig = {
    TRACES_INGESTION_CONSUMER_GROUP_ID: string
    TRACES_INGESTION_CONSUMER_CONSUME_TOPIC: string
    TRACES_INGESTION_CONSUMER_OVERFLOW_TOPIC: string
    TRACES_INGESTION_CONSUMER_DLQ_TOPIC: string
    TRACES_INGESTION_CONSUMER_CLICKHOUSE_TOPIC: string
    TRACES_REDIS_HOST: string
    TRACES_REDIS_PORT: number
    TRACES_REDIS_PASSWORD: string
    TRACES_REDIS_TLS: boolean
    TRACES_LIMITER_ENABLED_TEAMS: string
    TRACES_LIMITER_DISABLED_FOR_TEAMS: string
    TRACES_LIMITER_BUCKET_SIZE_KB: number
    TRACES_LIMITER_REFILL_RATE_KB_PER_SECOND: number
    TRACES_LIMITER_TTL_SECONDS: number
    TRACES_LIMITER_TEAM_BUCKET_SIZE_KB: string
    TRACES_LIMITER_TEAM_REFILL_RATE_KB_PER_SECOND: string
    REDIS_URL: string
    REDIS_POOL_MIN_SIZE: number
    REDIS_POOL_MAX_SIZE: number
    KAFKA_CLIENT_RACK: string | undefined
}

export function getDefaultTracesIngestionConsumerConfig(): TracesIngestionConsumerConfig {
    return {
        TRACES_INGESTION_CONSUMER_GROUP_ID: 'ingestion-traces',
        TRACES_INGESTION_CONSUMER_CONSUME_TOPIC: KAFKA_TRACES_INGESTION,
        TRACES_INGESTION_CONSUMER_OVERFLOW_TOPIC: KAFKA_TRACES_INGESTION_OVERFLOW,
        TRACES_INGESTION_CONSUMER_DLQ_TOPIC: KAFKA_TRACES_INGESTION_DLQ,
        TRACES_INGESTION_CONSUMER_CLICKHOUSE_TOPIC: KAFKA_TRACES_CLICKHOUSE,
        TRACES_REDIS_HOST: '127.0.0.1',
        TRACES_REDIS_PORT: 6379,
        TRACES_REDIS_PASSWORD: '',
        TRACES_REDIS_TLS: isProdEnv() ? true : false,
        TRACES_LIMITER_ENABLED_TEAMS: isProdEnv() ? '' : '*',
        TRACES_LIMITER_DISABLED_FOR_TEAMS: '',
        TRACES_LIMITER_BUCKET_SIZE_KB: 10000,
        TRACES_LIMITER_REFILL_RATE_KB_PER_SECOND: 1000,
        TRACES_LIMITER_TTL_SECONDS: 60 * 60 * 24,
        TRACES_LIMITER_TEAM_BUCKET_SIZE_KB: '',
        TRACES_LIMITER_TEAM_REFILL_RATE_KB_PER_SECOND: '',
        // Overlapping fields with CommonConfig, included for standalone usage
        // ok to connect to localhost over plaintext
        // nosemgrep: trailofbits.generic.redis-unencrypted-transport.redis-unencrypted-transport
        REDIS_URL: 'redis://127.0.0.1',
        REDIS_POOL_MIN_SIZE: 1,
        REDIS_POOL_MAX_SIZE: 3,
        KAFKA_CLIENT_RACK: undefined,
    }
}
