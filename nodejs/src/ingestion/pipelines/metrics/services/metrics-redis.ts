import { RedisV2, createRedisV2PoolFromConfig } from '~/common/redis/redis-v2'
import { MetricsIngestionConsumerConfig } from '~/ingestion/pipelines/metrics/config'

export type MetricsRedisConfig = Pick<
    MetricsIngestionConsumerConfig,
    | 'METRICS_REDIS_HOST'
    | 'METRICS_REDIS_PORT'
    | 'METRICS_REDIS_TLS'
    | 'METRICS_LIMITER_FAIL_OPEN'
    | 'REDIS_URL'
    | 'REDIS_POOL_MIN_SIZE'
    | 'REDIS_POOL_MAX_SIZE'
>

export const METRICS_LIMITER_FAIL_OPEN_REDIS_TIMEOUT_MS = 2_000

export function createMetricsRateLimiterRedis(config: MetricsRedisConfig): RedisV2 {
    const failOpen = config.METRICS_LIMITER_FAIL_OPEN
    // Without the offline queue, a command during an outage fails at once instead of piling up and
    // replaying stale limiter writes when Redis comes back.
    const failOpenOptions = failOpen
        ? {
              commandTimeout: METRICS_LIMITER_FAIL_OPEN_REDIS_TIMEOUT_MS,
              enableOfflineQueue: false,
              autoResendUnfulfilledCommands: false,
          }
        : {}
    return createRedisV2PoolFromConfig({
        connection: {
            ...(config.METRICS_REDIS_HOST
                ? {
                      url: config.METRICS_REDIS_HOST,
                      options: {
                          port: config.METRICS_REDIS_PORT,
                          tls: config.METRICS_REDIS_TLS ? {} : undefined,
                          ...failOpenOptions,
                      },
                      name: 'metrics-redis',
                  }
                : { url: config.REDIS_URL, options: failOpenOptions, name: 'metrics-redis-fallback' }),
            ...(failOpen ? { exitOnRepeatedErrors: false } : {}),
        },
        poolMinSize: config.REDIS_POOL_MIN_SIZE,
        poolMaxSize: config.REDIS_POOL_MAX_SIZE,
        ...(failOpen ? { acquireTimeoutMillis: METRICS_LIMITER_FAIL_OPEN_REDIS_TIMEOUT_MS } : {}),
    })
}
