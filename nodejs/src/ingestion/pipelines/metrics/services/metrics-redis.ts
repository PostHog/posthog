import { RedisV2, createRedisV2PoolFromConfig } from '~/common/redis/redis-v2'
import { MetricsIngestionConsumerConfig } from '~/ingestion/pipelines/metrics/config'

export type MetricsRedisConfig = Pick<
    MetricsIngestionConsumerConfig,
    | 'METRICS_REDIS_HOST'
    | 'METRICS_REDIS_PORT'
    | 'METRICS_REDIS_PASSWORD'
    | 'METRICS_REDIS_TLS'
    | 'REDIS_URL'
    | 'REDIS_POOL_MIN_SIZE'
    | 'REDIS_POOL_MAX_SIZE'
>

/** The dedicated Redis the token-bucket rate limiter uses, falling back to the shared `REDIS_URL`. */
export function createMetricsRateLimiterRedis(config: MetricsRedisConfig): RedisV2 {
    return createRedisV2PoolFromConfig({
        connection: config.METRICS_REDIS_HOST
            ? {
                  url: config.METRICS_REDIS_HOST,
                  options: {
                      port: config.METRICS_REDIS_PORT,
                      password: config.METRICS_REDIS_PASSWORD || undefined,
                      tls: config.METRICS_REDIS_TLS ? {} : undefined,
                  },
                  name: 'metrics-redis',
              }
            : { url: config.REDIS_URL, name: 'metrics-redis-fallback' },
        poolMinSize: config.REDIS_POOL_MIN_SIZE,
        poolMaxSize: config.REDIS_POOL_MAX_SIZE,
    })
}
