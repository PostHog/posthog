import { LRUCache } from 'lru-cache'

import { RedisPool } from '../../types'
import { logger } from '../../utils/logger'
import { Limiter } from '../../utils/token-bucket'
import { SESSION_FILTER_REDIS_TTL_SECONDS } from '../constants'
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
        }
    }

    /**
     * Check if a session is blocked.
     *
     * Fails open: if Redis is unavailable, assumes the session is not blocked.
     *
     * @param teamId - The team ID
     * @param sessionId - The session ID
     * @returns true if the session is blocked, false otherwise
     */
    public async isBlocked(teamId: number, sessionId: string): Promise<boolean> {
        // Skip Redis entirely when filter is disabled
        if (!this.filterEnabled) {
            return false
        }

        const key = this.generateKey(teamId, sessionId)

        // Check local cache first to avoid Redis round-trip
        const cached = this.localCache.get(key)
        if (cached !== undefined) {
            SessionBatchMetrics.incrementSessionFilterCacheHit()
            return cached
        }

        SessionBatchMetrics.incrementSessionFilterCacheMiss()

        let client
        try {
            client = await this.redisPool.acquire()
            const exists = await client.exists(key)
            const isBlocked = exists === 1

            // Cache the result locally to prevent repeated Redis calls
            // Cache both blocked and not-blocked states
            this.localCache.set(key, isBlocked)

            return isBlocked
        } catch (error) {
            // Fail open: if Redis is unavailable, allow the session through
            logger.error('session_filter_is_blocked_redis_error', {
                teamId,
                sessionId,
                error: String(error),
            })
            SessionBatchMetrics.incrementSessionFilterRedisErrors()
            return false
        } finally {
            if (client) {
                await this.redisPool.release(client)
            }
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
