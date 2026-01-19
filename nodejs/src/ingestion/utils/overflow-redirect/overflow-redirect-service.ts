import { Pool as GenericPool } from 'generic-pool'
import { Redis } from 'ioredis'

import { HealthCheckResult, HealthCheckResultError, HealthCheckResultOk } from '../../../types'
import { timeoutGuard } from '../../../utils/db/utils'
import { logger } from '../../../utils/logger'

export type OverflowType = 'events' | 'recordings' | 'llm'

export interface OverflowEventKey {
    token: string
    distinctId: string
}

export interface OverflowEventBatch {
    key: OverflowEventKey
    eventCount: number
    firstTimestamp: number
}

/**
 * Service for handling stateful overflow redirects.
 * Implementations differ based on lane type (main vs overflow).
 */
export interface OverflowRedirectService {
    /**
     * Handle a batch of events grouped by token:distinct_id.
     *
     * - Main lane: Check if flagged, flag if rate limited, return set of keys to redirect
     * - Overflow lane: Refresh TTL for all keys, return empty set (no redirects)
     *
     * @returns Set of keys (token:distinctId) that should be redirected to overflow
     */
    handleEventBatch(type: OverflowType, batch: OverflowEventBatch[]): Promise<Set<string>>

    /**
     * Health check for the service
     */
    healthCheck(): Promise<HealthCheckResult>

    /**
     * Graceful shutdown
     */
    shutdown(): Promise<void>
}

/**
 * Base configuration shared by all overflow redirect implementations.
 */
export interface BaseOverflowRedirectConfig {
    redisPool: GenericPool<Redis>
    redisTTLSeconds: number
}

/**
 * Abstract base class with common functionality for overflow redirect services.
 */
export abstract class BaseOverflowRedirectService implements OverflowRedirectService {
    protected static readonly REDIS_KEY_PREFIX = '@posthog/stateful-overflow/'

    protected redisPool: GenericPool<Redis>
    protected redisTTLSeconds: number

    constructor(config: BaseOverflowRedirectConfig) {
        this.redisPool = config.redisPool
        this.redisTTLSeconds = config.redisTTLSeconds
    }

    /**
     * Generate Redis key for a given type, token, and distinctId.
     */
    protected redisKey(type: OverflowType, token: string, distinctId: string): string {
        return `${BaseOverflowRedirectService.REDIS_KEY_PREFIX}${type}:${token}:${distinctId}`
    }

    /**
     * Generate member key (token:distinctId) used in result sets.
     */
    protected memberKey(token: string, distinctId: string): string {
        return `${token}:${distinctId}`
    }

    /**
     * Execute a Redis operation with proper pool management and error handling.
     * Acquires client from pool, executes operation, and releases back to pool.
     * Errors are logged but not thrown (fail-open behavior).
     */
    protected async withRedisClient<T>(
        operation: string,
        context: Record<string, unknown>,
        fn: (client: Redis) => Promise<T>,
        defaultValue: T
    ): Promise<T> {
        let client: Redis | undefined
        const timeout = timeoutGuard(`${operation} delayed. Waiting over 30 sec.`, context)

        try {
            client = await this.redisPool.acquire()
            return await fn(client)
        } catch (error) {
            logger.warn(`Redis error in ${operation}, failing open`, { error, ...context })
            return defaultValue
        } finally {
            clearTimeout(timeout)
            if (client) {
                try {
                    await this.redisPool.release(client)
                } catch (releaseError) {
                    logger.warn('Failed to release Redis client', { error: releaseError })
                }
            }
        }
    }

    abstract handleEventBatch(type: OverflowType, batch: OverflowEventBatch[]): Promise<Set<string>>

    async healthCheck(): Promise<HealthCheckResult> {
        let client: Redis | undefined
        try {
            client = await this.redisPool.acquire()
            await client.ping()
            return new HealthCheckResultOk()
        } catch (error) {
            return new HealthCheckResultError('OverflowRedirectService is down', { error })
        } finally {
            if (client) {
                try {
                    await this.redisPool.release(client)
                } catch {
                    // Ignore release errors in health check
                }
            }
        }
    }

    abstract shutdown(): Promise<void>
}
