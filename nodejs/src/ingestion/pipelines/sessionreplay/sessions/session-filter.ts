import { LRUCache } from 'lru-cache'

import { logger } from '~/common/utils/logger'
import { Limiter } from '~/common/utils/token-bucket'
import { SESSION_FILTER_REDIS_TTL_SECONDS } from '~/ingestion/pipelines/sessionreplay/constants'
import { SessionSet } from '~/ingestion/pipelines/sessionreplay/shared/session-map'
import { RedisPool } from '~/types'

import { SessionBatchMetrics } from './metrics'

const DEFAULT_LOCAL_CACHE_MAX_SIZE = 100_000

export interface SessionFilterConfig {
    redisPool: RedisPool
    bucketCapacity: number
    bucketReplenishRate: number
    /** When true, rate-limited sessions are blocked. When false, metrics are tracked but no blocking occurs (dry run mode). */
    blockingEnabled: boolean
    /** When false, skips all Redis calls entirely. Use to bypass Redis during outages. */
    filterEnabled: boolean
    localCacheTtlMs: number
    localCacheMaxSize?: number
    /**
     * Optional Redis key namespace. Omit for the main lane (keeps the prefix exactly
     * `@posthog/replay/session-blocked`). A secondary pipeline (e.g. the ML mirror) must pass its own
     * namespace so its blocklist doesn't collide with the main lane's.
     */
    keyNamespace?: string
}

/**
 * Manages session filtering and rate limiting for new sessions.
 *
 * Responsibilities:
 * - Rate limiting new sessions per team using a token bucket
 * - Maintaining a blocklist of sessions that should be dropped
 * - When a new session is rate-limited, blocking the entire session
 *   to prevent half-ingested recordings
 *
 * The blocklist is persisted in Redis with an in-memory LRU cache
 * to minimize Redis round-trips.
 *
 * ## Failure policy
 *
 * This class only does rate limiting — it never influences the encryption key — so every Redis op here
 * follows rule 1 (see {@link SessionTracker}'s class doc): fail OPEN. On a Redis error we degrade toward
 * under-counting / under-blocking (letting sessions through), never toward over-counting or halting the
 * pipeline. Concretely: {@link isBlocked} assumes not-blocked, {@link blockSessions} keeps the block in
 * the local cache but doesn't persist it, and the in-memory token bucket in {@link handleNewSessions}
 * needs no Redis at all. Contrast the tracker's {@link SessionTracker.hasSeen}, which is key-integrity
 * critical and therefore fails hard.
 */
export class SessionFilter {
    private readonly keyPrefix: string

    // In-memory cache to avoid hitting Redis for every message
    // Since Kafka partitions by session ID, the same session always hits the same consumer
    // Maps key -> blocked status (true = blocked, false = not blocked but checked)
    private readonly localCache: LRUCache<string, boolean>

    private readonly redisPool: RedisPool
    private readonly sessionLimiter: Limiter
    private readonly blockingEnabled: boolean
    private readonly filterEnabled: boolean

    constructor(config: SessionFilterConfig) {
        this.keyPrefix = config.keyNamespace
            ? `@posthog/replay/${config.keyNamespace}/session-blocked`
            : '@posthog/replay/session-blocked'
        this.redisPool = config.redisPool
        this.sessionLimiter = new Limiter(config.bucketCapacity, config.bucketReplenishRate)
        this.blockingEnabled = config.blockingEnabled
        this.filterEnabled = config.filterEnabled

        this.localCache = new LRUCache({
            max: config.localCacheMaxSize ?? DEFAULT_LOCAL_CACHE_MAX_SIZE,
            ttl: config.localCacheTtlMs,
        })
    }

    /**
     * Block sessions so all their future messages are dropped, persisting the whole set to Redis in
     * one pipelined round trip.
     *
     * Fails open (rate-limiting rule 1): if Redis is unavailable, the sessions aren't persisted to the
     * blocklist but are still blocked locally for this consumer. The worst case is under-blocking on
     * other consumers — never over-counting, and never halting.
     *
     * @param sessions - The sessions to block
     */
    private async blockSessions(sessions: SessionSet): Promise<void> {
        // Block locally first so it holds even if the Redis write fails.
        for (const { teamId, sessionId } of sessions) {
            this.localCache.set(this.generateKey(teamId, sessionId), true)
            SessionBatchMetrics.incrementSessionsBlocked()
        }

        const startTime = performance.now()
        let client
        try {
            client = await this.redisPool.acquire()
            const pipeline = client.pipeline()
            for (const { teamId, sessionId } of sessions) {
                pipeline.set(this.generateKey(teamId, sessionId), '1', 'EX', SESSION_FILTER_REDIS_TTL_SECONDS)
            }
            await pipeline.exec()

            logger.info('session_filter_blocked_sessions', { count: sessions.size })
        } catch (error) {
            // Fail open: log the error but don't throw. The sessions are still blocked locally.
            logger.error('session_filter_block_sessions_redis_error', {
                count: sessions.size,
                error: String(error),
            })
            SessionBatchMetrics.incrementSessionFilterRedisErrors()
        } finally {
            if (client) {
                await this.redisPool.release(client)
            }
            SessionBatchMetrics.observeSessionFilterRedisLatency((performance.now() - startTime) / 1000)
        }
    }

    /**
     * Return which of the given sessions are blocked. Local-cache hits are answered without Redis; the
     * remaining sessions are checked in a single MGET.
     *
     * Fails open (rate-limiting rule 1): if Redis is unavailable, the unknown sessions are assumed not
     * blocked, so a rate-limited session may slip through and record — under-enforcement, never halting.
     *
     * @returns the subset of `sessions` that are blocked (an unblocked session is simply absent)
     */
    public async isBlocked(sessions: SessionSet): Promise<SessionSet> {
        const blocked = new SessionSet()

        // Skip Redis entirely when filter is disabled — nothing is blocked.
        if (!this.filterEnabled) {
            return blocked
        }

        const misses: { teamId: number; sessionId: string }[] = []
        for (const { teamId, sessionId } of sessions) {
            // Check local cache first to avoid a Redis round-trip. Both blocked and not-blocked states
            // are cached; a later block updates the cache via blockSession.
            const cached = this.localCache.get(this.generateKey(teamId, sessionId))
            if (cached !== undefined) {
                SessionBatchMetrics.incrementSessionFilterCacheHit()
                if (cached) {
                    blocked.add(teamId, sessionId)
                }
            } else {
                SessionBatchMetrics.incrementSessionFilterCacheMiss()
                misses.push({ teamId, sessionId })
            }
        }

        if (misses.length === 0) {
            return blocked
        }

        const startTime = performance.now()
        let client
        try {
            client = await this.redisPool.acquire()
            const values = await client.mget(misses.map(({ teamId, sessionId }) => this.generateKey(teamId, sessionId)))
            for (let i = 0; i < misses.length; i++) {
                const { teamId, sessionId } = misses[i]
                const isBlocked = values[i] !== null
                this.localCache.set(this.generateKey(teamId, sessionId), isBlocked)
                if (isBlocked) {
                    blocked.add(teamId, sessionId)
                }
            }
            return blocked
        } catch (error) {
            // Fail open: if Redis is unavailable, treat the unknown sessions as not blocked by omitting
            // them from the set (their block state stays unknown rather than halting the pipeline).
            logger.error('session_filter_is_blocked_redis_error', { error: String(error) })
            SessionBatchMetrics.incrementSessionFilterRedisErrors()
            return blocked
        } finally {
            if (client) {
                await this.redisPool.release(client)
            }
            SessionBatchMetrics.observeSessionFilterRedisLatency((performance.now() - startTime) / 1000)
        }
    }

    /**
     * Handle a batch of new sessions by checking each against its team's rate limit and blocking the
     * ones that exceed it. The rate-limit check is an in-memory token bucket, so the only Redis cost is
     * one pipelined write for whichever sessions get blocked.
     *
     * Should be called with the genuinely-new sessions only — those neither seen nor already blocked —
     * so a session already on the blocklist isn't charged a second token.
     *
     * @param sessions - The new sessions to rate-limit
     * @returns the sessions this call blocked, so the caller can gate them without a second isBlocked read
     */
    public async handleNewSessions(sessions: SessionSet): Promise<SessionSet> {
        const toBlock = new SessionSet()
        for (const { teamId, sessionId } of sessions) {
            const isAllowed = this.sessionLimiter.consume(String(teamId), 1)
            if (isAllowed) {
                continue
            }
            logger.debug('session_filter_new_session_rate_limited', {
                teamId,
                sessionId,
                blockingEnabled: this.blockingEnabled,
            })
            SessionBatchMetrics.incrementNewSessionsRateLimited(teamId)
            if (this.blockingEnabled && this.filterEnabled) {
                toBlock.add(teamId, sessionId)
            }
        }

        if (toBlock.size > 0) {
            await this.blockSessions(toBlock)
        }

        return toBlock
    }

    private generateKey(teamId: number, sessionId: string): string {
        return `${this.keyPrefix}:${teamId}:${sessionId}`
    }
}
