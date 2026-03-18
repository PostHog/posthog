import { Pool as GenericPool } from 'generic-pool'
import { Redis } from 'ioredis'

import { HealthCheckResult, HealthCheckResultError, HealthCheckResultOk } from '../../../types'
import { timeoutGuard } from '../../../utils/db/utils'
import { logger } from '../../../utils/logger'
import { overflowRedirectRedisLatency, overflowRedirectRedisOpsTotal } from './metrics'

export type OverflowType = 'events' | 'recordings' | 'llm'

const REDIS_KEY_PREFIX = '@posthog/stateful-overflow/'

/**
 * Generates a Redis key for a given type, token, and distinctId.
 */
export function redisKey(type: OverflowType, token: string, distinctId: string): string {
    return `${REDIS_KEY_PREFIX}${type}:${token}:${distinctId}`
}

/**
 * Generates a member key (token:distinctId) used in result sets.
 */
export function memberKey(token: string, distinctId: string): string {
    return `${token}:${distinctId}`
}

/**
 * Repository for overflow redirect Redis operations.
 *
 * Owns pool management, key formatting, and all Redis I/O.
 * All operations fail open: errors are logged and default values returned.
 */
export interface OverflowRedisRepository {
    /**
     * Batch check which keys exist in Redis using MGET.
     * Returns a Map of memberKey -> isFlagged.
     */
    batchCheck(type: OverflowType, keys: { token: string; distinctId: string }[]): Promise<Map<string, boolean>>

    /**
     * Batch flag keys in Redis using pipeline SET with EX (TTL).
     */
    batchFlag(type: OverflowType, keys: { token: string; distinctId: string }[]): Promise<void>

    /**
     * Batch refresh TTL for keys using pipeline GETEX.
     * Only refreshes existing keys, does not create new ones.
     */
    batchRefreshTTL(type: OverflowType, keys: { token: string; distinctId: string }[]): Promise<void>

    /**
     * Health check: PING Redis.
     */
    healthCheck(): Promise<HealthCheckResult>
}

export interface OverflowRedisRepositoryConfig {
    redisPool: GenericPool<Redis>
    redisTTLSeconds: number
}

export class RedisOverflowRepository implements OverflowRedisRepository {
    private redisPool: GenericPool<Redis>
    private redisTTLSeconds: number

    constructor(config: OverflowRedisRepositoryConfig) {
        this.redisPool = config.redisPool
        this.redisTTLSeconds = config.redisTTLSeconds
    }

    async batchCheck(type: OverflowType, keys: { token: string; distinctId: string }[]): Promise<Map<string, boolean>> {
        const defaultResult = new Map<string, boolean>()
        for (const key of keys) {
            defaultResult.set(memberKey(key.token, key.distinctId), false)
        }

        if (keys.length === 0) {
            return defaultResult
        }

        const startTime = performance.now()
        const result = await this.withRedisClient(
            'batchCheckRedis',
            { type, count: keys.length },
            async (client: Redis) => {
                const results = new Map<string, boolean>()
                const redisKeys = keys.map((key) => redisKey(type, key.token, key.distinctId))
                const values = await client.mget(...redisKeys)

                for (let i = 0; i < keys.length; i++) {
                    results.set(memberKey(keys[i].token, keys[i].distinctId), values[i] !== null)
                }

                overflowRedirectRedisOpsTotal.labels('mget', 'success').inc()
                return results
            },
            defaultResult
        )

        const latencySeconds = (performance.now() - startTime) / 1000
        overflowRedirectRedisLatency.labels('mget').observe(latencySeconds)

        if (result === defaultResult && keys.length > 0) {
            overflowRedirectRedisOpsTotal.labels('mget', 'error').inc()
        }

        return result
    }

    async batchFlag(type: OverflowType, keys: { token: string; distinctId: string }[]): Promise<void> {
        if (keys.length === 0) {
            return
        }

        const startTime = performance.now()
        let succeeded = false

        await this.withRedisClient(
            'batchFlagInRedis',
            { type, count: keys.length },
            async (client: Redis) => {
                const pipeline = client.pipeline()

                for (const key of keys) {
                    pipeline.set(redisKey(type, key.token, key.distinctId), '1', 'EX', this.redisTTLSeconds)
                }

                await pipeline.exec()
                succeeded = true
                overflowRedirectRedisOpsTotal.labels('set', 'success').inc()
            },
            undefined
        )

        const latencySeconds = (performance.now() - startTime) / 1000
        overflowRedirectRedisLatency.labels('set').observe(latencySeconds)

        if (!succeeded) {
            overflowRedirectRedisOpsTotal.labels('set', 'error').inc()
        }
    }

    async batchRefreshTTL(type: OverflowType, keys: { token: string; distinctId: string }[]): Promise<void> {
        if (keys.length === 0) {
            return
        }

        const startTime = performance.now()
        let succeeded = false

        await this.withRedisClient(
            'batchRefreshTTL',
            { type, count: keys.length },
            async (client: Redis) => {
                const pipeline = client.pipeline()

                for (const key of keys) {
                    pipeline.getex(redisKey(type, key.token, key.distinctId), 'EX', this.redisTTLSeconds)
                }

                await pipeline.exec()
                succeeded = true
                overflowRedirectRedisOpsTotal.labels('getex', 'success').inc()
            },
            undefined
        )

        const latencySeconds = (performance.now() - startTime) / 1000
        overflowRedirectRedisLatency.labels('getex').observe(latencySeconds)

        if (!succeeded) {
            overflowRedirectRedisOpsTotal.labels('getex', 'error').inc()
        }
    }

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

    private async withRedisClient<T>(
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
}
