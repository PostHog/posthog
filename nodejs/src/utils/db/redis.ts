import { createPool } from 'generic-pool'
import Redis, { Cluster, RedisOptions } from 'ioredis'

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
    /**
     * When true, construct an ioredis Cluster client (uses CLUSTER NODES discovery from the
     * seed endpoint) instead of a standalone Redis client. Required for ElastiCache cluster mode.
     * The returned client is API-compatible with the standalone Redis type for the methods we use.
     */
    clusterMode?: boolean
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
    return createRedisClient(config.url, config.options, config.name, config.clusterMode)
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

/**
 * Convert a URL or bare hostname into an ioredis Cluster seed-node descriptor. ElastiCache
 * cluster endpoints discover the rest of the topology via CLUSTER NODES, so a single seed is
 * enough.
 */
function parseClusterSeedNode(url: string, options?: RedisOptions): { host: string; port: number } {
    const fallbackPort = options?.port ?? 6379
    try {
        const parsed = new URL(url)
        return {
            host: parsed.hostname || url,
            port: parsed.port ? parseInt(parsed.port, 10) : fallbackPort,
        }
    } catch {
        const [host, portStr] = url.split(':')
        return { host, port: portStr ? parseInt(portStr, 10) : fallbackPort }
    }
}

export async function createRedisClient(
    url: string,
    options?: RedisOptions,
    connectionName?: string,
    clusterMode?: boolean
): Promise<Redis.Redis> {
    // Cast Cluster as Redis.Redis: the Cluster client implements the same command surface for
    // single-key ops, EVALSHA, defineCommand, scan/info/quit. Multi-key commands (MGET/MSET) and
    // SCAN must be handled cluster-aware at the call site (split per slot or per master node).
    const redis = clusterMode
        ? (new Cluster([parseClusterSeedNode(url, options)], {
              redisOptions: { ...options, maxRetriesPerRequest: -1 },
              enableReadyCheck: true,
          }) as unknown as Redis.Redis)
        : new Redis(url, {
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
                logger.info('✅', `${connectionId}Connected to Redis${clusterMode ? ' cluster' : ''}!`, redisHost)
            }
        })
    await redis.info()
    return redis
}
