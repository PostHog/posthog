import { createPool } from 'generic-pool'
import Redis, { RedisOptions } from 'ioredis'

import { RedisPool } from '../../types'
import { logger } from '../../utils/logger'
import { killGracefully } from '../../utils/utils'
import { captureException } from '../posthog'

/** Number of Redis error events until the server is killed gracefully. */
const REDIS_ERROR_COUNTER_LIMIT = 10

/**
 * Configuration for a Redis connection.
 * Consumers should build this config inline where they create Redis connections,
 * rather than relying on centralized builder functions.
 */
export interface RedisConnectionConfig {
    url: string
    options?: RedisOptions
    name?: string
}

/**
 * Configuration needed to create Redis pool instances.
 */
export interface RedisPoolConfig {
    connection: RedisConnectionConfig
    poolMinSize: number
    poolMaxSize: number
}

export async function createRedisFromConfig(config: RedisConnectionConfig): Promise<Redis.Redis> {
    return createRedisClient(config.url, config.options, config.name)
}

export function createRedisPoolFromConfig(config: RedisPoolConfig): RedisPool {
    return createPool<Redis.Redis>(
        {
            create: () => createRedisFromConfig(config.connection),
            destroy: async (client) => {
                await client.quit()
            },
        },
        {
            min: config.poolMinSize,
            max: config.poolMaxSize,
            autostart: true,
        }
    )
}

/**
 * Sanitizes a Redis URL for safe logging by extracting only the host portion.
 * This prevents leaking credentials that may be embedded in the URL.
 */
function getRedisHost(url: string, options?: RedisOptions): string {
    try {
        const parsed = new URL(url)
        return parsed.host || '[sanitized-redis-host]'
    } catch {
        const atIndex = url.lastIndexOf('@')
        const hostname = atIndex >= 0 ? url.substring(atIndex + 1) : url
        if (options?.port && !hostname.includes(':')) {
            return `${hostname}:${options.port}`
        }
        return hostname
    }
}

export async function createRedisClient(
    url: string,
    options?: RedisOptions,
    connectionName?: string
): Promise<Redis.Redis> {
    const redis = new Redis(url, {
        ...options,
        maxRetriesPerRequest: -1,
    })
    let errorCounter = 0
    const redisHost = getRedisHost(url, options)
    const connectionId = connectionName ? `[${connectionName}] ` : ''
    const creationStack = new Error().stack
    redis
        .on('error', (error) => {
            errorCounter++
            captureException(error)
            if (errorCounter > REDIS_ERROR_COUNTER_LIMIT) {
                logger.error(
                    '😡',
                    `${connectionId}Redis error encountered! host: ${redisHost} Enough of this, I quit!`,
                    { error, creationStack }
                )
                killGracefully()
            } else {
                logger.error(
                    '🔴',
                    `${connectionId}Redis error encountered! host: ${redisHost} Trying to reconnect...`,
                    { error, creationStack }
                )
            }
        })
        .on('ready', () => {
            if (process.env.NODE_ENV !== 'test') {
                logger.info('✅', `${connectionId}Connected to Redis!`, redisHost)
            }
        })
    await redis.info()
    return redis
}
