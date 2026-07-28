import { createPool } from 'generic-pool'
import Redis, { RedisOptions } from 'ioredis'

import { RedisPool } from '~/types'

import { logger } from '../../utils/logger'
import { killGracefully } from '../../utils/utils'
import { captureException } from '../posthog'

/** Number of Redis error events until the server is killed gracefully. */
const REDIS_ERROR_COUNTER_LIMIT = 10

/**
 * ioredis error codes for transient connection/DNS problems that self-recover on reconnect.
 * With `maxRetriesPerRequest: -1` a short blip (e.g. a `getaddrinfo ENOTFOUND` DNS hiccup)
 * emits a burst of these before recovering, so we log them but hold off on reporting until
 * the error counter shows Redis is genuinely unreachable.
 */
const TRANSIENT_REDIS_ERROR_CODES = new Set(['ENOTFOUND', 'ECONNREFUSED', 'ECONNRESET', 'ETIMEDOUT', 'EAI_AGAIN'])

function isTransientConnectionError(error: unknown): boolean {
    const code = (error as { code?: unknown } | null)?.code
    return typeof code === 'string' && TRANSIENT_REDIS_ERROR_CODES.has(code)
}

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
 * Scope entry for a `RedisPool`. `start` creates the pool (which connects
 * to Redis eagerly via `autostart`), `stop` drains the pool then clears
 * it so all connections are released.
 */
export class RedisPoolComponent {
    constructor(private readonly config: RedisPoolConfig) {}

    start(): Promise<{ value: RedisPool; stop: () => Promise<void> }> {
        const pool = createRedisPoolFromConfig(this.config)
        return Promise.resolve({
            value: pool,
            stop: async (): Promise<void> => {
                await pool.drain()
                await pool.clear()
            },
        })
    }
}

/**
 * Sanitizes a Redis URL for safe logging by extracting only the host portion.
 * This prevents leaking credentials that may be embedded in the URL.
 */
export function getRedisHost(url: string, options?: RedisOptions): string {
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
    let killing = false
    const redisHost = getRedisHost(url, options)
    const connectionId = connectionName ? `[${connectionName}] ` : ''
    const creationStack = new Error().stack
    redis
        .on('error', (error) => {
            // Once we've decided to quit, stop re-reporting and re-signalling on every
            // subsequent reconnect error while the process winds down — otherwise a single
            // outage produces a storm of identical captured exceptions.
            if (killing) {
                return
            }
            errorCounter++
            const overLimit = errorCounter > REDIS_ERROR_COUNTER_LIMIT
            // Expected transient connection/DNS errors self-recover on reconnect. Capturing each
            // one turns a short blip into a storm of identical exceptions, so below the limit we
            // only log them — a genuinely-down Redis still surfaces once the counter crosses it.
            if (overLimit || !isTransientConnectionError(error)) {
                captureException(error)
            }
            if (overLimit) {
                killing = true
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
