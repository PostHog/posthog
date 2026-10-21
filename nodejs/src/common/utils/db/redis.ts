import { createPool } from 'generic-pool'
import Redis, { RedisOptions } from 'ioredis'

import { RedisPool } from '~/types'

import { logger } from '../../utils/logger'
import { killGracefully } from '../../utils/utils'
import { captureException } from '../posthog'

/** Number of Redis error events until the server is killed gracefully. */
const REDIS_ERROR_COUNTER_LIMIT = 10
const NON_FATAL_CONNECT_TIMEOUT_MS = 10_000

/**
 * Configuration for a Redis connection.
 * Consumers should build this config inline where they create Redis connections,
 * rather than relying on centralized builder functions.
 */
export interface RedisConnectionConfig {
    url: string
    options?: RedisOptions
    name?: string
    /**
     * Stops the process after repeated connection errors. Defaults to true. Set it to false for an
     * optional store, so an outage of that store does not take down every route of the service.
     * A client that cannot connect is then closed, and its caller sees the error.
     */
    exitOnRepeatedErrors?: boolean
}

/**
 * Configuration needed to create Redis pool instances.
 */
export interface RedisPoolConfig {
    connection: RedisConnectionConfig
    poolMinSize: number
    poolMaxSize: number
    /**
     * Rejects a caller that waits this long for a connection. Prefer this to racing `acquire()`
     * against your own timer: generic-pool has no cancellation, so a caller that walks away from a
     * pending `acquire()` is still handed the next free connection and is still counted as
     * borrowing it. Enough of those and the pool is empty for good.
     */
    acquireTimeoutMillis?: number
}

export async function createRedisFromConfig(config: RedisConnectionConfig): Promise<Redis.Redis> {
    return createRedisClient(config.url, config.options, config.name, config.exitOnRepeatedErrors ?? true)
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
            ...(config.acquireTimeoutMillis !== undefined ? { acquireTimeoutMillis: config.acquireTimeoutMillis } : {}),
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
    connectionName?: string,
    exitOnRepeatedErrors: boolean = true
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
            // A non-fatal client reconnects on every error, so only its first error is reported.
            if (exitOnRepeatedErrors || errorCounter === 1) {
                captureException(error)
            }
            if (exitOnRepeatedErrors && errorCounter > REDIS_ERROR_COUNTER_LIMIT) {
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
    try {
        if (exitOnRepeatedErrors) {
            await redis.info()
        } else {
            // A command waits offline while the client reconnects, so commandTimeout never starts for it.
            let timer: NodeJS.Timeout | undefined
            await Promise.race([
                redis.info(),
                new Promise<never>((_, reject) => {
                    timer = setTimeout(
                        () => reject(new Error(`${connectionId}Redis did not connect`)),
                        options?.commandTimeout ?? NON_FATAL_CONNECT_TIMEOUT_MS
                    )
                }),
            ]).finally(() => clearTimeout(timer))
        }
    } catch (error) {
        if (!exitOnRepeatedErrors) {
            // Nothing holds this client, so it would otherwise reconnect forever.
            redis.disconnect()
        }
        throw error
    }
    return redis
}
