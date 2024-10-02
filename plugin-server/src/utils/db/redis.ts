import * as Sentry from '@sentry/node'
import { createPool } from 'generic-pool'
import Redis, { RedisOptions } from 'ioredis'

import { PluginsServerConfig, RedisPool } from '../../types'
import { status } from '../../utils/status'
import { killGracefully } from '../../utils/utils'

/** Number of Redis error events until the server is killed gracefully. */
const REDIS_ERROR_COUNTER_LIMIT = 10

export async function createRedisPostHog(serverConfig: PluginsServerConfig): Promise<Redis.Redis> {
    const params = serverConfig.POSTHOG_REDIS_HOST
        ? {
              host: serverConfig.POSTHOG_REDIS_HOST,
              port: serverConfig.POSTHOG_REDIS_PORT,
              password: serverConfig.POSTHOG_REDIS_PASSWORD,
          }
        : undefined

    return createRedisClient(params ? params.host : serverConfig.REDIS_URL, params)
}

export async function createRedisIngestion(serverConfig: PluginsServerConfig): Promise<Redis.Redis> {
    // TRICKY: We added the INGESTION_REDIS_HOST later to free up POSTHOG_REDIS_HOST to be clear that it is
    // the shared django redis, hence we fallback to it if not set.

    const params = serverConfig.INGESTION_REDIS_HOST
        ? {
              host: serverConfig.INGESTION_REDIS_HOST,
              port: serverConfig.INGESTION_REDIS_PORT,
              password: serverConfig.INGESTION_REDIS_PASSWORD,
          }
        : serverConfig.POSTHOG_REDIS_HOST
        ? {
              host: serverConfig.POSTHOG_REDIS_HOST,
              port: serverConfig.POSTHOG_REDIS_PORT,
              password: serverConfig.POSTHOG_REDIS_PASSWORD,
          }
        : undefined

    return createRedisClient(params ? params.host : serverConfig.REDIS_URL, params)
}

export async function createRedisSessionRecording(serverConfig: PluginsServerConfig): Promise<Redis.Redis> {
    const params = serverConfig.POSTHOG_SESSION_RECORDING_REDIS_HOST
        ? {
              host: serverConfig.POSTHOG_SESSION_RECORDING_REDIS_HOST,
              port: serverConfig.POSTHOG_SESSION_RECORDING_REDIS_PORT,
          }
        : undefined

    return createRedisClient(params ? params.host : serverConfig.REDIS_URL, params)
}

export async function createRedisClient(url: string, options?: RedisOptions): Promise<Redis.Redis> {
    const redis = new Redis(url, {
        ...options,
        maxRetriesPerRequest: -1,
    })
    let errorCounter = 0
    redis
        .on('error', (error) => {
            errorCounter++
            Sentry.captureException(error)
            if (errorCounter > REDIS_ERROR_COUNTER_LIMIT) {
                status.error('😡', 'Redis error encountered! Enough of this, I quit!\n', error)
                killGracefully()
            } else {
                status.error('🔴', 'Redis error encountered! Trying to reconnect...\n', error)
            }
        })
        .on('ready', () => {
            if (process.env.NODE_ENV !== 'test') {
                status.info('✅', 'Connected to Redis!')
            }
        })
    await redis.info()
    return redis
}

export function createRedisPool(
    options: Pick<PluginsServerConfig, 'REDIS_POOL_MIN_SIZE' | 'REDIS_POOL_MAX_SIZE'>,
    create: () => Promise<Redis.Redis>
): RedisPool {
    return createPool<Redis.Redis>(
        {
            create,
            destroy: async (client) => {
                await client.quit()
            },
        },
        {
            min: options.REDIS_POOL_MIN_SIZE,
            max: options.REDIS_POOL_MAX_SIZE,
            autostart: true,
        }
    )
}
