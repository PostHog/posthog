import { KafkaDownstreamProducerEnvConfig } from '@posthog/ingestion-common/outputs/producers'
import { CommonConfig } from '@posthog/node-common/config'
import { KafkaBrokerConfig, RedisConnectionsConfig } from '@posthog/node-common/config/connections'
import { BaseServerConfig } from '@posthog/node-common/servers/base-server'
import { RedisPool } from '@posthog/node-common/types'
import { PostgresRouterConfig } from '@posthog/node-common/utils/db/postgres'
import { RedisConnectionConfig, createRedisPoolFromConfig } from '@posthog/node-common/utils/db/redis'
import { SessionReplayOutputsConfig } from '@posthog/replay-storage/config'
import { KafkaSessionreplayProducerEnvConfig } from '@posthog/replay-storage/outputs/producer-config'

import { SessionRecordingIngesterConfig } from './consumer'

export type IngestionSessionReplayServerConfig = BaseServerConfig &
    SessionRecordingIngesterConfig &
    KafkaBrokerConfig &
    KafkaDownstreamProducerEnvConfig &
    KafkaSessionreplayProducerEnvConfig &
    SessionReplayOutputsConfig &
    RedisConnectionsConfig &
    PostgresRouterConfig &
    Pick<
        CommonConfig,
        'LOG_LEVEL' | 'PLUGIN_SERVER_MODE' | 'HEALTHCHECK_MAX_STALE_SECONDS' | 'KAFKA_HEALTHCHECK_SECONDS'
    >

/**
 * Builds the session-recording and restriction Redis pools a replay deployment needs.
 *
 * `sessionRecordingConnection` overrides where the session-recording pool points, for a lane that
 * runs against its own instance. The override belongs here rather than at the call site because
 * these pools connect eagerly (`autostart`), so a caller that built both and then discarded one
 * would leave a connected pool that nothing owns and nothing drains on shutdown.
 */
export function buildSessionReplayRedisPools(
    config: IngestionSessionReplayServerConfig,
    sessionRecordingConnection?: RedisConnectionConfig | null
): {
    redisPool: RedisPool
    restrictionRedisPool: RedisPool
} {
    const redisPool = createRedisPoolFromConfig({
        connection:
            sessionRecordingConnection ??
            (config.POSTHOG_SESSION_RECORDING_REDIS_HOST
                ? {
                      url: config.POSTHOG_SESSION_RECORDING_REDIS_HOST,
                      options: {
                          port: config.POSTHOG_SESSION_RECORDING_REDIS_PORT ?? 6379,
                          commandTimeout: config.SESSION_RECORDING_REDIS_TIMEOUT_MS,
                      },
                      name: 'session-recording-redis',
                  }
                : {
                      url: config.REDIS_URL,
                      options: { commandTimeout: config.SESSION_RECORDING_REDIS_TIMEOUT_MS },
                      name: 'session-recording-redis-fallback',
                  }),
        poolMinSize: config.REDIS_POOL_MIN_SIZE,
        poolMaxSize: config.REDIS_POOL_MAX_SIZE,
    })

    const restrictionRedisPool = createRedisPoolFromConfig({
        connection: config.INGESTION_REDIS_HOST
            ? {
                  url: config.INGESTION_REDIS_HOST,
                  options: { port: config.INGESTION_REDIS_PORT },
                  name: 'ingestion-redis',
              }
            : config.POSTHOG_REDIS_HOST
              ? {
                    url: config.POSTHOG_REDIS_HOST,
                    options: { port: config.POSTHOG_REDIS_PORT, password: config.POSTHOG_REDIS_PASSWORD },
                    name: 'ingestion-redis',
                }
              : { url: config.REDIS_URL, name: 'ingestion-redis' },
        poolMinSize: config.REDIS_POOL_MIN_SIZE,
        poolMaxSize: config.REDIS_POOL_MAX_SIZE,
    })

    return { redisPool, restrictionRedisPool }
}
