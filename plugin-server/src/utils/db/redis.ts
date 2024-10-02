import * as Sentry from '@sentry/node'
import { createPool } from 'generic-pool'
import Redis, { RedisOptions } from 'ioredis'

import { PluginsServerConfig, RedisPool } from '../../types'
import { status } from '../../utils/status'
import { killGracefully } from '../../utils/utils'

/** Number of Redis error events until the server is killed gracefully. */
const REDIS_ERROR_COUNTER_LIMIT = 10

export type REDIS_SERVER_KIND = 'posthog' | 'ingestion' | 'session-recording'

export async function createRedis(serverConfig: PluginsServerConfig, kind: REDIS_SERVER_KIND): Promise<Redis.Redis> {
    let params: { host: string; port: number; password?: string } | undefined
    switch (kind) {
        case 'posthog':
            // The shared redis instance used by django, celery etc.
            params = serverConfig.POSTHOG_REDIS_HOST
                ? {
                      host: serverConfig.POSTHOG_REDIS_HOST,
                      port: serverConfig.POSTHOG_REDIS_PORT,
                      password: serverConfig.POSTHOG_REDIS_PASSWORD,
                  }
                : undefined
        case 'ingestion':
            // The dedicated ingestion redis instance.

            // TRICKY: We added the INGESTION_REDIS_HOST later to free up POSTHOG_REDIS_HOST to be clear that it is
            // the shared django redis, hence we fallback to it if not set.
            params = serverConfig.INGESTION_REDIS_HOST
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
        case 'session-recording':
            // The dedicated session recording redis instance
            params = serverConfig.POSTHOG_SESSION_RECORDING_REDIS_HOST
                ? {
                      host: serverConfig.POSTHOG_SESSION_RECORDING_REDIS_HOST,
                      port: serverConfig.POSTHOG_SESSION_RECORDING_REDIS_PORT ?? 6379,
                  }
                : undefined
    }

    // Fallback to REDIS_URL if not set (primarily for docker compose)
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
