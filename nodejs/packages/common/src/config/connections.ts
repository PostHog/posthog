import type { CommonConfig } from '~/config'
import type { PostgresRouterConfig } from '~/utils/db/postgres'

export type KafkaBrokerConfig = Pick<
    CommonConfig,
    | 'KAFKA_HOSTS'
    | 'KAFKA_CLIENT_RACK'
    | 'KAFKA_CLIENT_CERT_B64'
    | 'KAFKA_CLIENT_CERT_KEY_B64'
    | 'KAFKA_TRUSTED_CERT_B64'
    | 'KAFKA_SASL_MECHANISM'
    | 'KAFKA_SASL_USER'
    | 'KAFKA_SASL_PASSWORD'
>

/** PostgreSQL connection config for a service — excludes behavioral cohorts */
export type DatabaseConnectionConfig = Omit<PostgresRouterConfig, 'BEHAVIORAL_COHORTS_DATABASE_URL'>

/** Redis connection config — URLs, hosts, and pool sizing */
export type RedisConnectionsConfig = Pick<
    CommonConfig,
    | 'REDIS_URL'
    | 'REDIS_POOL_MIN_SIZE'
    | 'REDIS_POOL_MAX_SIZE'
    | 'INGESTION_REDIS_HOST'
    | 'INGESTION_REDIS_PORT'
    | 'POSTHOG_REDIS_HOST'
    | 'POSTHOG_REDIS_PORT'
    | 'POSTHOG_REDIS_PASSWORD'
>

/** Kafka consumer loop tuning config */
export type KafkaConsumerBaseConfig = Pick<
    CommonConfig,
    | 'CONSUMER_BATCH_SIZE'
    | 'CONSUMER_MAX_HEARTBEAT_INTERVAL_MS'
    | 'CONSUMER_LOOP_STALL_THRESHOLD_MS'
    | 'CONSUMER_LOG_STATS_LEVEL'
    | 'CONSUMER_LOOP_BASED_HEALTH_CHECK'
    | 'CONSUMER_MAX_BACKGROUND_TASKS'
    | 'CONSUMER_AUTO_CREATE_TOPICS'
>
