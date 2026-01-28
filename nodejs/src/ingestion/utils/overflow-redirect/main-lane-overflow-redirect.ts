import { HealthCheckResult } from '../../../types'
import { MemoryRateLimiter } from '../overflow-detector'
import {
    overflowRedirectCacheHitsTotal,
    overflowRedirectCacheSize,
    overflowRedirectEventsTotal,
    overflowRedirectKeysTotal,
    overflowRedirectRateLimitDecisions,
} from './metrics'
import { OverflowEventBatch, OverflowRedirectService } from './overflow-redirect-service'
import { OverflowRedisRepository, OverflowType, memberKey } from './overflow-redis-repository'

export interface MainLaneOverflowRedirectConfig {
    redisRepository: OverflowRedisRepository
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
export class MainLaneOverflowRedirect implements OverflowRedirectService {
    private localCache: Map<string, CacheEntry>
    private rateLimiter: MemoryRateLimiter
    private localCacheTTLSeconds: number
    private statefulEnabled: boolean
    private redisRepository: OverflowRedisRepository

    constructor(config: MainLaneOverflowRedirectConfig) {
        this.redisRepository = config.redisRepository
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
                    toRedirect.add(memberKey(event.key.token, event.key.distinctId))
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
                const redisResults = await this.redisRepository.batchCheck(
                    type,
                    needsRedisCheck.map((e) => e.key)
                )

                for (const event of needsRedisCheck) {
                    const mKey = memberKey(event.key.token, event.key.distinctId)
                    const cacheKey = this.localCacheKey(type, event.key.token, event.key.distinctId)

                    if (redisResults.get(mKey)) {
                        // Flagged in Redis - redirect
                        toRedirect.add(mKey)
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
            const rateLimitKey = memberKey(event.key.token, event.key.distinctId)
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
            await this.redisRepository.batchFlag(
                type,
                newlyFlagged.map((e) => e.key)
            )
        }

        // Record key-level metrics
        overflowRedirectKeysTotal.labels(type, 'redirected').inc(toRedirect.size)
        overflowRedirectKeysTotal.labels(type, 'passed').inc(batch.length - toRedirect.size)

        // Record event-level metrics
        let redirectedEvents = 0
        let passedEvents = 0
        for (const event of batch) {
            const mKey = memberKey(event.key.token, event.key.distinctId)
            if (toRedirect.has(mKey)) {
                redirectedEvents += event.eventCount
            } else {
                passedEvents += event.eventCount
            }
        }
        overflowRedirectEventsTotal.labels(type, 'redirected').inc(redirectedEvents)
        overflowRedirectEventsTotal.labels(type, 'passed').inc(passedEvents)

        return toRedirect
    }

    async healthCheck(): Promise<HealthCheckResult> {
        return this.redisRepository.healthCheck()
    }

    shutdown(): Promise<void> {
        this.localCache.clear()
        return Promise.resolve()
    }
}
