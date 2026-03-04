import type { CommonConfig } from '../common/config'
import { ConfigOf, defineConfig } from '../config/define-config'
import {
    KAFKA_LOGS_CLICKHOUSE,
    KAFKA_LOGS_INGESTION,
    KAFKA_LOGS_INGESTION_DLQ,
    KAFKA_LOGS_INGESTION_OVERFLOW,
} from '../config/kafka-topics'
import { isProdEnv } from '../utils/env-utils'

export const logsIngestionConsumerConfigDefs = defineConfig({
    LOGS_INGESTION_CONSUMER_GROUP_ID: () => 'ingestion-logs',
    LOGS_INGESTION_CONSUMER_CONSUME_TOPIC: () => KAFKA_LOGS_INGESTION,
    LOGS_INGESTION_CONSUMER_OVERFLOW_TOPIC: () => KAFKA_LOGS_INGESTION_OVERFLOW,
    LOGS_INGESTION_CONSUMER_DLQ_TOPIC: () => KAFKA_LOGS_INGESTION_DLQ,
    LOGS_INGESTION_CONSUMER_CLICKHOUSE_TOPIC: () => KAFKA_LOGS_CLICKHOUSE,
    LOGS_REDIS_HOST: () => '127.0.0.1',
    LOGS_REDIS_PORT: () => 6379,
    LOGS_REDIS_PASSWORD: () => '',
    LOGS_REDIS_TLS: () => isProdEnv(),
    LOGS_LIMITER_ENABLED_TEAMS: (): string => (isProdEnv() ? '' : '*'),
    LOGS_LIMITER_DISABLED_FOR_TEAMS: () => '',
    LOGS_LIMITER_BUCKET_SIZE_KB: () => 10000, // 10MB burst
    LOGS_LIMITER_REFILL_RATE_KB_PER_SECOND: () => 1000, // 1MB/second refill rate
    LOGS_LIMITER_TTL_SECONDS: () => 60 * 60 * 24,
    LOGS_LIMITER_TEAM_BUCKET_SIZE_KB: () => '',
    LOGS_LIMITER_TEAM_REFILL_RATE_KB_PER_SECOND: () => '',
})

// The old type included REDIS_URL, REDIS_POOL_MIN_SIZE, REDIS_POOL_MAX_SIZE, KAFKA_CLIENT_RACK
// which are owned by CommonConfig. We compose the type to maintain backward compatibility.
export type LogsIngestionConsumerConfig = ConfigOf<typeof logsIngestionConsumerConfigDefs> &
    Pick<CommonConfig, 'REDIS_URL' | 'REDIS_POOL_MIN_SIZE' | 'REDIS_POOL_MAX_SIZE' | 'KAFKA_CLIENT_RACK'>
