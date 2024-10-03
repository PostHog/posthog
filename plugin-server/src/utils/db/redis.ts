import * as Sentry from '@sentry/node'
import { createPool } from 'generic-pool'
import Redis, { RedisOptions } from 'ioredis'

import { PluginsServerConfig, RedisPool } from '../../types'
import { status } from '../../utils/status'
import { killGracefully } from '../../utils/utils'

/** Number of Redis error events until the server is killed gracefully. */
const REDIS_ERROR_COUNTER_LIMIT = 10

export type REDIS_SERVER_KIND = 'posthog' | 'ingestion' | 'session-recording'

export function getRedisConnectionOptions(
    serverConfig: PluginsServerConfig,
    kind: REDIS_SERVER_KIND
): {
    url: string
    options?: RedisOptions
} {
    const fallback = { url: serverConfig.REDIS_URL }
    switch (kind) {
        case 'posthog':
            return serverConfig.POSTHOG_REDIS_HOST
                ? {
                      url: serverConfig.POSTHOG_REDIS_HOST,
                      options: {
                          port: serverConfig.POSTHOG_REDIS_PORT,
                          password: serverConfig.POSTHOG_REDIS_PASSWORD,
                      },
                  }
                : fallback
        case 'ingestion':
            return serverConfig.INGESTION_REDIS_HOST
                ? {
                      url: serverConfig.INGESTION_REDIS_HOST,
                      options: {
                          port: serverConfig.INGESTION_REDIS_PORT,
                      },
                  }
                : serverConfig.POSTHOG_REDIS_HOST
                ? {
                      url: serverConfig.POSTHOG_REDIS_HOST,
                      options: {
                          port: serverConfig.POSTHOG_REDIS_PORT,
                          password: serverConfig.POSTHOG_REDIS_PASSWORD,
                      },
                  }
                : fallback
        case 'session-recording':
            return serverConfig.POSTHOG_SESSION_RECORDING_REDIS_HOST
                ? {
                      url: serverConfig.POSTHOG_SESSION_RECORDING_REDIS_HOST ?? 'localhost',
                      options: {
                          port: serverConfig.POSTHOG_SESSION_RECORDING_REDIS_PORT ?? 6379,
                      },
                  }
                : fallback
    }
}

export async function createRedis(serverConfig: PluginsServerConfig, kind: REDIS_SERVER_KIND): Promise<Redis.Redis> {
    const { url, options } = getRedisConnectionOptions(serverConfig, kind)
    return createRedisClient(url, options)
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

export function createRedisPool(options: PluginsServerConfig, kind: REDIS_SERVER_KIND): RedisPool {
    return createPool<Redis.Redis>(
        {
            create: () => createRedis(options, kind),
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
