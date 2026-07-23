import { LRUCache } from 'lru-cache'

import { MemoryRateLimiter } from '~/ingestion/common/overflow-redirect/overflow-detector'
import { Component } from '~/ingestion/common/scopes'
import { HealthCheckResult } from '~/types'

import {
    overflowRedirectCacheHitsTotal,
    overflowRedirectCacheSize,
    overflowRedirectEventsTotal,
    overflowRedirectKeysTotal,
    overflowRedirectRateLimitDecisions,
    overflowRedirectSourceEventsTotal,
} from './metrics'
import { OverflowEventGroup, OverflowRedirectService } from './overflow-redirect-service'
import { OverflowRedisRepository, OverflowType, memberKey } from './overflow-redis-repository'
import { OverflowStrategyEntry } from './overflow-strategy'

export interface MainLaneOverflowRedirectConfig {
    redisRepository: OverflowRedisRepository
    localCacheTTLSeconds: number
    /** Max entries in the in-memory flagged/not-flagged cache before LRU eviction. */
    localCacheMaxSize?: number
    /** Overflow conditions to enforce; a key is redirected when any strategy's bucket is exhausted. */
    strategies: OverflowStrategyEntry[]
    /** Redis keyspace this service operates on. Fixed per pipeline. */
    overflowType: OverflowType
}

// Bounds the in-memory cache so a flood of unique token:distinct_id keys cannot
// grow it without limit; evicted keys simply re-check Redis on the next lookup.
const DEFAULT_LOCAL_CACHE_MAX_SIZE = 1_000_000

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
    private localCache: LRUCache<string, boolean>
    private strategies: {
        label: string
        countTokens: OverflowStrategyEntry['countTokens']
        limiter: MemoryRateLimiter
    }[]
    private redisRepository: OverflowRedisRepository
    private overflowType: OverflowType

    constructor(config: MainLaneOverflowRedirectConfig) {
        this.redisRepository = config.redisRepository
        this.localCache = new LRUCache({
            max: config.localCacheMaxSize ?? DEFAULT_LOCAL_CACHE_MAX_SIZE,
            ttl: config.localCacheTTLSeconds * 1000,
        })
        this.strategies = config.strategies.map((entry) => ({
            label: entry.label,
            countTokens: entry.countTokens,
            limiter: new MemoryRateLimiter(entry.bucketCapacity, entry.replenishRate),
        }))
        this.overflowType = config.overflowType
    }

    private localCacheKey(type: OverflowType, token: string, distinctId: string): string {
        return `${type}:${token}:${distinctId}`
    }

    // true = flagged in Redis, false = known not in Redis, undefined = cache miss.
    // TTL expiry and size-bounded LRU eviction are handled by the cache itself.
    private getCachedValue(key: string): boolean | undefined {
        return this.localCache.get(key)
    }

    private setCachedValue(key: string, value: boolean): void {
        this.localCache.set(key, value)
    }

    async handleEventBatch(batch: OverflowEventGroup[]): Promise<Set<string>> {
        const type = this.overflowType
        const toRedirect = new Set<string>()
        const redirectSource = new Map<string, 'redis' | 'rate_limiter'>()
        const needsRateLimitCheck: OverflowEventGroup[] = []

        // Step 1: Check local cache
        const needsRedisCheck: OverflowEventGroup[] = []

        for (const group of batch) {
            const cacheKey = this.localCacheKey(type, group.key.token, group.key.distinctId)
            const cached = this.getCachedValue(cacheKey)

            if (cached === true) {
                // Already flagged (cached from previous Redis lookup) - redirect
                const mKey = memberKey(group.key.token, group.key.distinctId)
                toRedirect.add(mKey)
                redirectSource.set(mKey, 'redis')
                overflowRedirectCacheHitsTotal.labels(type, 'hit_flagged').inc()
            } else if (cached === false) {
                // Known not in Redis - check rate limit only
                needsRateLimitCheck.push(group)
                overflowRedirectCacheHitsTotal.labels(type, 'hit_not_flagged').inc()
            } else {
                // Cache miss - need to check Redis
                needsRedisCheck.push(group)
                overflowRedirectCacheHitsTotal.labels(type, 'miss').inc()
            }
        }

        // Step 2: Batch check Redis for cache misses using MGET
        if (needsRedisCheck.length > 0) {
            const redisResults = await this.redisRepository.batchCheck(
                type,
                needsRedisCheck.map((e) => e.key)
            )

            for (const group of needsRedisCheck) {
                const mKey = memberKey(group.key.token, group.key.distinctId)
                const cacheKey = this.localCacheKey(type, group.key.token, group.key.distinctId)

                if (redisResults.get(mKey)) {
                    // Flagged in Redis - redirect
                    toRedirect.add(mKey)
                    redirectSource.set(mKey, 'redis')
                    this.setCachedValue(cacheKey, true)
                } else {
                    // Not in Redis - cache false and check rate limit
                    this.setCachedValue(cacheKey, false)
                    needsRateLimitCheck.push(group)
                }
            }
        }

        // Update cache size metric
        overflowRedirectCacheSize.set(this.localCache.size)

        // Step 3: Check rate limiter for unflagged keys
        const newlyFlagged: OverflowEventGroup[] = []

        for (const group of needsRateLimitCheck) {
            const rateLimitKey = memberKey(group.key.token, group.key.distinctId)

            // Consume from every strategy (no short-circuit) so buckets drain
            // consistently; any exhausted bucket flags the key.
            let allowed = true
            for (const { label, countTokens, limiter } of this.strategies) {
                let tokens = 0
                for (const headers of group.headersPerEvent) {
                    tokens += countTokens(headers)
                }
                if (tokens === 0) {
                    continue
                }

                if (limiter.consume(rateLimitKey, tokens, group.firstTimestamp)) {
                    overflowRedirectRateLimitDecisions.labels(type, label, 'allowed').inc()
                } else {
                    allowed = false
                    overflowRedirectRateLimitDecisions.labels(type, label, 'exceeded').inc()
                }
            }

            if (!allowed) {
                // Rate limit exceeded - needs to be flagged
                newlyFlagged.push(group)
                toRedirect.add(rateLimitKey)
                redirectSource.set(rateLimitKey, 'rate_limiter')
            }
        }

        // Step 4: Batch flag newly rate-limited keys in Redis
        if (newlyFlagged.length > 0) {
            // Update local cache BEFORE Redis write to prevent race condition where
            // a subsequent batch could check the rate limiter again before Redis completes
            for (const group of newlyFlagged) {
                const cacheKey = this.localCacheKey(type, group.key.token, group.key.distinctId)
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
        const eventsBySource = new Map<'redis' | 'rate_limiter', number>()
        for (const group of batch) {
            const mKey = memberKey(group.key.token, group.key.distinctId)
            if (toRedirect.has(mKey)) {
                redirectedEvents += group.headersPerEvent.length
                const source = redirectSource.get(mKey)
                if (source) {
                    eventsBySource.set(source, (eventsBySource.get(source) ?? 0) + group.headersPerEvent.length)
                }
            } else {
                passedEvents += group.headersPerEvent.length
            }
        }
        overflowRedirectEventsTotal.labels(type, 'redirected').inc(redirectedEvents)
        overflowRedirectEventsTotal.labels(type, 'passed').inc(passedEvents)

        // Record redirect source metrics
        for (const [source, count] of eventsBySource) {
            overflowRedirectSourceEventsTotal.labels(type, source).inc(count)
        }

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

/** Scope component for the main-lane overflow redirect (rate-limiting). */
export class MainLaneOverflowRedirectComponent implements Component<OverflowRedirectService> {
    constructor(private readonly config: MainLaneOverflowRedirectConfig) {}

    start(): Promise<{ value: OverflowRedirectService; stop: () => Promise<void> }> {
        const service = new MainLaneOverflowRedirect(this.config)
        return Promise.resolve({ value: service, stop: () => service.shutdown() })
    }
}
