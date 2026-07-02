import { LRUCache } from 'lru-cache'

import { logger } from '~/common/utils/logger'
import { Limiter } from '~/common/utils/token-bucket'
import { SESSION_FILTER_REDIS_TTL_SECONDS } from '~/ingestion/pipelines/sessionreplay/constants'
import { SessionMap, SessionSet } from '~/ingestion/pipelines/sessionreplay/shared/session-map'
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
 */
export class SessionFilter {
    private readonly keyPrefix = '@posthog/replay/session-blocked'

    // In-memory cache to avoid hitting Redis for every message
    // Since Kafka partitions by session ID, the same session always hits the same consumer
    // Maps key -> blocked status (true = blocked, false = not blocked but checked)
    private readonly localCache: LRUCache<string, boolean>

    private readonly redisPool: RedisPool
    private readonly sessionLimiter: Limiter
    private readonly blockingEnabled: boolean
    private readonly filterEnabled: boolean

    constructor(config: SessionFilterConfig) {
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
     * Block a session so all future messages are dropped.
     *
     * Fails open: if Redis is unavailable, the session won't be persisted
     * to the blocklist but will still be blocked locally for this consumer.
     *
     * @param teamId - The team ID
     * @param sessionId - The session ID to block
     */
    private async blockSession(teamId: number, sessionId: string): Promise<void> {
        const key = this.generateKey(teamId, sessionId)

        // Add to local cache immediately for fast lookups
        // This ensures blocking works even if Redis fails
        this.localCache.set(key, true)
        SessionBatchMetrics.incrementSessionsBlocked()

        const startTime = performance.now()
        let client
        try {
            client = await this.redisPool.acquire()
            await client.set(key, '1', 'EX', SESSION_FILTER_REDIS_TTL_SECONDS)

            logger.info('session_filter_blocked_session', {
                teamId,
                sessionId,
            })
        } catch (error) {
            // Fail open: log the error but don't throw
            // The session is still blocked locally via the cache
            logger.error('session_filter_block_session_redis_error', {
                teamId,
                sessionId,
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
     * Check which of the given sessions are blocked. Local-cache hits are answered without Redis; the
     * remaining sessions are checked in a single MGET.
     *
     * Fails open: if Redis is unavailable, the unknown sessions are assumed not blocked.
     *
     * @returns a map keyed by `(teamId, sessionId)` — true if blocked, false otherwise
     */
    public async isBlocked(sessions: SessionSet): Promise<SessionMap<boolean>> {
        const result = new SessionMap<boolean>()

        // Skip Redis entirely when filter is disabled
        if (!this.filterEnabled) {
            for (const { teamId, sessionId } of sessions) {
                result.set(teamId, sessionId, false)
            }
            return result
        }

        const misses: { teamId: number; sessionId: string }[] = []
        for (const { teamId, sessionId } of sessions) {
            // Check local cache first to avoid a Redis round-trip. Both blocked and not-blocked states
            // are cached; a later block updates the cache via blockSession.
            const cached = this.localCache.get(this.generateKey(teamId, sessionId))
            if (cached !== undefined) {
                SessionBatchMetrics.incrementSessionFilterCacheHit()
                result.set(teamId, sessionId, cached)
            } else {
                SessionBatchMetrics.incrementSessionFilterCacheMiss()
                misses.push({ teamId, sessionId })
            }
        }

        if (misses.length === 0) {
            return result
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
                result.set(teamId, sessionId, isBlocked)
            }
            return result
        } catch (error) {
            // Fail open: if Redis is unavailable, allow the unknown sessions through
            logger.error('session_filter_is_blocked_redis_error', { error: String(error) })
            SessionBatchMetrics.incrementSessionFilterRedisErrors()
            for (const { teamId, sessionId } of misses) {
                result.set(teamId, sessionId, false)
            }
            return result
        } finally {
            if (client) {
                await this.redisPool.release(client)
            }
            SessionBatchMetrics.observeSessionFilterRedisLatency((performance.now() - startTime) / 1000)
        }
    }

    /**
     * Handle a new session by checking rate limits and blocking if necessary.
     *
     * This method should be called for new sessions (as determined by SessionTracker).
     * If the team has exceeded its rate limit and rate limiting is enabled,
     * the session will be blocked. The caller should then check isBlocked() to
     * determine whether to process the message.
     *
     * @param teamId - The team ID
     * @param sessionId - The session ID
     */
    public async handleNewSession(teamId: number, sessionId: string): Promise<void> {
        const isAllowed = this.sessionLimiter.consume(String(teamId), 1)

        if (!isAllowed) {
            logger.debug('session_filter_new_session_rate_limited', {
                teamId,
                sessionId,
                blockingEnabled: this.blockingEnabled,
            })
            SessionBatchMetrics.incrementNewSessionsRateLimited(teamId)

            if (this.blockingEnabled && this.filterEnabled) {
                await this.blockSession(teamId, sessionId)
            }
        }
    }

    private generateKey(teamId: number, sessionId: string): string {
        return `${this.keyPrefix}:${teamId}:${sessionId}`
    }
}
