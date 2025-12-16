import { createPool } from 'generic-pool'
import Redis, { RedisOptions } from 'ioredis'

import { PluginsServerConfig, RedisPool } from '../../types'
import { logger } from '../../utils/logger'
import { killGracefully } from '../../utils/utils'
import { captureException } from '../posthog'

/** Number of Redis error events until the server is killed gracefully. */
const REDIS_ERROR_COUNTER_LIMIT = 10

export type REDIS_SERVER_KIND = 'posthog' | 'ingestion' | 'session-recording' | 'cookieless' | 'cdp' | 'logs'

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
                      url: serverConfig.POSTHOG_SESSION_RECORDING_REDIS_HOST,
                      options: {
                          port: serverConfig.POSTHOG_SESSION_RECORDING_REDIS_PORT ?? 6379,
                      },
                  }
                : fallback
        case 'cookieless':
            return serverConfig.COOKIELESS_REDIS_HOST
                ? {
                      url: serverConfig.COOKIELESS_REDIS_HOST,
                      options: {
                          port: serverConfig.COOKIELESS_REDIS_PORT ?? 6379,
                      },
                  }
                : fallback
        case 'cdp':
            return serverConfig.CDP_REDIS_HOST
                ? {
                      url: serverConfig.CDP_REDIS_HOST,
                      options: {
                          port: serverConfig.CDP_REDIS_PORT,
                          password: serverConfig.CDP_REDIS_PASSWORD,
                      },
                  }
                : fallback
        case 'logs':
            return serverConfig.LOGS_REDIS_HOST
                ? {
                      url: serverConfig.LOGS_REDIS_HOST,
                      options: {
                          port: serverConfig.LOGS_REDIS_PORT,
                          // TLS is an object that lets you define certificate, ca, etc
                          // we just want the default config so weirdly we pass empty object to enable it
                          tls: serverConfig.LOGS_REDIS_TLS ? {} : undefined,
                      },
                  }
                : fallback
    }
}

export async function createRedis(serverConfig: PluginsServerConfig, kind: REDIS_SERVER_KIND): Promise<Redis.Redis> {
    const { url, options } = getRedisConnectionOptions(serverConfig, kind)
    return createRedisClient(url, options)
}

/**
 * Sanitizes a Redis URL for safe logging by extracting only the host portion.
 * This prevents leaking credentials that may be embedded in the URL.
 * 
 * @param url - Redis URL (e.g., 'redis://:password@localhost:6379') or plain hostname (e.g., 'posthog-redis')
 * @returns The host portion without credentials (e.g., 'localhost:6379'), or the plain hostname if not a URL
 */
function getRedisHost(url: string): string {
    try {
        const parsed = new URL(url)
        // Return host (includes port) if available, otherwise fallback to hostname (excludes port)
        // Both exclude credentials by design. If both are empty, return a safe placeholder
        return parsed.host || parsed.hostname || '[redis-host]'
    } catch {
        // If URL parsing fails, strip any potential credentials from the string
        // Use lastIndexOf to handle multiple @ symbols (e.g., 'user:pass@host:pass@domain')
        const atIndex = url.lastIndexOf('@')
        return atIndex >= 0 ? url.substring(atIndex + 1) : url
    }
}

export async function createRedisClient(url: string, options?: RedisOptions): Promise<Redis.Redis> {
    const redis = new Redis(url, {
        ...options,
        maxRetriesPerRequest: -1,
    })
    let errorCounter = 0
    const redisHost = getRedisHost(url)
    redis
        .on('error', (error) => {
            errorCounter++
            captureException(error)
            if (errorCounter > REDIS_ERROR_COUNTER_LIMIT) {
                logger.error('😡', 'Redis error encountered! host:', redisHost, ' Enough of this, I quit!', error)
                killGracefully()
            } else {
                logger.error('🔴', 'Redis error encountered! host:', redisHost, ' Trying to reconnect...', error)
            }
        })
        .on('ready', () => {
            if (process.env.NODE_ENV !== 'test') {
                logger.info('✅', 'Connected to Redis!', redisHost)
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
