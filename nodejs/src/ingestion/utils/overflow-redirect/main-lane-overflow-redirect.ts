import { Redis } from 'ioredis'

import { MemoryRateLimiter } from '../overflow-detector'
import {
    overflowRedirectCacheHitsTotal,
    overflowRedirectCacheSize,
    overflowRedirectEventsTotal,
    overflowRedirectKeysTotal,
    overflowRedirectRateLimitDecisions,
    overflowRedirectRedisLatency,
    overflowRedirectRedisOpsTotal,
} from './metrics'
import {
    BaseOverflowRedirectConfig,
    BaseOverflowRedirectService,
    OverflowEventBatch,
    OverflowType,
} from './overflow-redirect-service'

export interface MainLaneOverflowRedirectConfig extends BaseOverflowRedirectConfig {
    statefulEnabled: boolean
    localCacheTTLSeconds: number
    bucketCapacity: number
    replenishRate: number
}

interface CacheEntry {
    value: boolean | null // true = flagged, null = known not in Redis
    expiresAt: number
}

/**
 * Main lane implementation of overflow redirect.
 *
 * For each batch of events:
 * 1. Check local cache for known flagged keys
 * 2. Batch query Redis (MGET) for cache misses
 * 3. Check rate limiter for unflagged keys
 * 4. Batch flag newly rate-limited keys in Redis (pipeline SET with EX)
 * 5. Return set of keys to redirect to overflow
 *
 * Uses individual Redis keys with native TTL expiry (no ZSET).
 */
export class MainLaneOverflowRedirect extends BaseOverflowRedirectService {
    private localCache: Map<string, CacheEntry>
    private rateLimiter: MemoryRateLimiter
    private localCacheTTLSeconds: number
    private statefulEnabled: boolean

    constructor(config: MainLaneOverflowRedirectConfig) {
        super(config)
        this.localCache = new Map()
        this.rateLimiter = new MemoryRateLimiter(config.bucketCapacity, config.replenishRate)
        this.localCacheTTLSeconds = config.localCacheTTLSeconds
        this.statefulEnabled = config.statefulEnabled
    }

    private localCacheKey(type: OverflowType, token: string, distinctId: string): string {
        return `${type}:${token}:${distinctId}`
    }

    private getCachedValue(key: string): boolean | null | undefined {
        const entry = this.localCache.get(key)
        if (!entry) {
            return undefined // cache miss
        }
        if (Date.now() > entry.expiresAt) {
            this.localCache.delete(key)
            return undefined // expired
        }
        return entry.value
    }

    private setCachedValue(key: string, value: boolean | null): void {
        this.localCache.set(key, {
            value,
            expiresAt: Date.now() + this.localCacheTTLSeconds * 1000,
        })
    }

    async handleEventBatch(type: OverflowType, batch: OverflowEventBatch[]): Promise<Set<string>> {
        const toRedirect = new Set<string>()
        const needsRateLimitCheck: OverflowEventBatch[] = []

        if (this.statefulEnabled) {
            // Step 1: Check local cache (stateful only)
            const needsRedisCheck: OverflowEventBatch[] = []

            for (const event of batch) {
                const cacheKey = this.localCacheKey(type, event.key.token, event.key.distinctId)
                const cached = this.getCachedValue(cacheKey)

                if (cached === true) {
                    // Already flagged - redirect
                    toRedirect.add(this.memberKey(event.key.token, event.key.distinctId))
                    overflowRedirectCacheHitsTotal.labels(type, 'hit_flagged').inc()
                } else if (cached === null) {
                    // Known not in Redis - check rate limit only
                    needsRateLimitCheck.push(event)
                    overflowRedirectCacheHitsTotal.labels(type, 'hit_not_flagged').inc()
                } else {
                    // Cache miss - need to check Redis
                    needsRedisCheck.push(event)
                    overflowRedirectCacheHitsTotal.labels(type, 'miss').inc()
                }
            }

            // Step 2: Batch check Redis for cache misses using MGET (stateful only)
            if (needsRedisCheck.length > 0) {
                const redisResults = await this.batchCheckRedis(type, needsRedisCheck)

                for (const event of needsRedisCheck) {
                    const memberKey = this.memberKey(event.key.token, event.key.distinctId)
                    const cacheKey = this.localCacheKey(type, event.key.token, event.key.distinctId)

                    if (redisResults.get(memberKey)) {
                        // Flagged in Redis - redirect
                        toRedirect.add(memberKey)
                        this.setCachedValue(cacheKey, true)
                    } else {
                        // Not in Redis - cache null and check rate limit
                        this.setCachedValue(cacheKey, null)
                        needsRateLimitCheck.push(event)
                    }
                }
            }

            // Update cache size metric
            overflowRedirectCacheSize.set(this.localCache.size)
        } else {
            // Stateless: all events need rate limit check
            needsRateLimitCheck.push(...batch)
        }

        // Step 3: Check rate limiter for unflagged keys
        const newlyFlagged: OverflowEventBatch[] = []

        for (const event of needsRateLimitCheck) {
            const rateLimitKey = this.memberKey(event.key.token, event.key.distinctId)
            const allowed = this.rateLimiter.consume(rateLimitKey, event.eventCount, event.firstTimestamp)

            if (!allowed) {
                // Rate limit exceeded - needs to be flagged
                newlyFlagged.push(event)
                toRedirect.add(rateLimitKey)
                overflowRedirectRateLimitDecisions.labels(type, 'exceeded').inc()
            } else {
                overflowRedirectRateLimitDecisions.labels(type, 'allowed').inc()
            }
        }

        // Step 4: Batch flag newly rate-limited keys in Redis (stateful only)
        if (this.statefulEnabled && newlyFlagged.length > 0) {
            // Update local cache BEFORE Redis write to prevent race condition where
            // a subsequent batch could check the rate limiter again before Redis completes
            for (const event of newlyFlagged) {
                const cacheKey = this.localCacheKey(type, event.key.token, event.key.distinctId)
                this.setCachedValue(cacheKey, true)
            }
            overflowRedirectCacheSize.set(this.localCache.size)

            // Async Redis write - cache already updated so concurrent batches will see the flag
            await this.batchFlagInRedis(type, newlyFlagged)
        }

        // Record key-level metrics
        overflowRedirectKeysTotal.labels(type, 'redirected').inc(toRedirect.size)
        overflowRedirectKeysTotal.labels(type, 'passed').inc(batch.length - toRedirect.size)

        // Record event-level metrics
        let redirectedEvents = 0
        let passedEvents = 0
        for (const event of batch) {
            const memberKey = this.memberKey(event.key.token, event.key.distinctId)
            if (toRedirect.has(memberKey)) {
                redirectedEvents += event.eventCount
            } else {
                passedEvents += event.eventCount
            }
        }
        overflowRedirectEventsTotal.labels(type, 'redirected').inc(redirectedEvents)
        overflowRedirectEventsTotal.labels(type, 'passed').inc(passedEvents)

        return toRedirect
    }

    /**
     * Batch check Redis using MGET.
     * Returns a Map of memberKey -> isFlagged (true if key exists)
     */
    private async batchCheckRedis(type: OverflowType, events: OverflowEventBatch[]): Promise<Map<string, boolean>> {
        const defaultResult = new Map<string, boolean>()
        for (const event of events) {
            defaultResult.set(this.memberKey(event.key.token, event.key.distinctId), false)
        }

        const startTime = performance.now()
        const result = await this.withRedisClient(
            'batchCheckRedis',
            { type, count: events.length },
            async (client: Redis) => {
                const results = new Map<string, boolean>()

                // Build array of Redis keys
                const redisKeys = events.map((event) => this.redisKey(type, event.key.token, event.key.distinctId))

                // MGET returns array of values (or null for missing keys)
                const values = await client.mget(...redisKeys)

                // Process results
                for (let i = 0; i < events.length; i++) {
                    const memberKey = this.memberKey(events[i].key.token, events[i].key.distinctId)
                    // Key exists if value is not null
                    results.set(memberKey, values[i] !== null)
                }

                overflowRedirectRedisOpsTotal.labels('mget', 'success').inc()
                return results
            },
            defaultResult
        )

        // Record latency regardless of success/failure
        const latencySeconds = (performance.now() - startTime) / 1000
        overflowRedirectRedisLatency.labels('mget').observe(latencySeconds)

        // If we got the default result, it means Redis failed
        if (result === defaultResult && events.length > 0) {
            overflowRedirectRedisOpsTotal.labels('mget', 'error').inc()
        }

        return result
    }

    /**
     * Batch flag keys in Redis using pipeline of SET commands with EX (TTL).
     */
    private async batchFlagInRedis(type: OverflowType, events: OverflowEventBatch[]): Promise<void> {
        const startTime = performance.now()
        let succeeded = false

        await this.withRedisClient(
            'batchFlagInRedis',
            { type, count: events.length },
            async (client: Redis) => {
                const pipeline = client.pipeline()

                // Queue SET with EX for each event
                for (const event of events) {
                    const key = this.redisKey(type, event.key.token, event.key.distinctId)
                    pipeline.set(key, '1', 'EX', this.redisTTLSeconds)
                }

                await pipeline.exec()
                succeeded = true
                overflowRedirectRedisOpsTotal.labels('set', 'success').inc()
            },
            undefined
        )

        // Record latency and error metrics
        const latencySeconds = (performance.now() - startTime) / 1000
        overflowRedirectRedisLatency.labels('set').observe(latencySeconds)

        if (!succeeded) {
            overflowRedirectRedisOpsTotal.labels('set', 'error').inc()
        }
    }

    async shutdown(): Promise<void> {
        // Clear local cache
        this.localCache.clear()
        return Promise.resolve()
    }
}
