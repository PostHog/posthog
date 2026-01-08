import { LRUCache } from 'lru-cache'

import { RedisPool } from '../../types'
import { logger } from '../../utils/logger'
import { Limiter } from '../../utils/token-bucket'
import { SESSION_FILTER_REDIS_TTL_SECONDS } from '../constants'
import { SessionBatchMetrics } from './metrics'

const DEFAULT_LOCAL_CACHE_MAX_SIZE = 100_000

export interface SessionFilterConfig {
    redisPool: RedisPool
    sessionLimiter: Limiter
    rateLimitEnabled: boolean
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
    private readonly rateLimitEnabled: boolean

    constructor(config: SessionFilterConfig) {
        this.redisPool = config.redisPool
        this.sessionLimiter = config.sessionLimiter
        this.rateLimitEnabled = config.rateLimitEnabled

        this.localCache = new LRUCache({
            max: config.localCacheMaxSize ?? DEFAULT_LOCAL_CACHE_MAX_SIZE,
            ttl: config.localCacheTtlMs,
        })
    }

    /**
     * Block a session so all future messages are dropped.
     *
     * @param teamId - The team ID
     * @param sessionId - The session ID to block
     */
    private async blockSession(teamId: number, sessionId: string): Promise<void> {
        const key = this.generateKey(teamId, sessionId)

        // Add to local cache immediately for fast lookups
        this.localCache.set(key, true)

        const client = await this.redisPool.acquire()

        try {
            await client.set(key, '1', 'EX', SESSION_FILTER_REDIS_TTL_SECONDS)

            SessionBatchMetrics.incrementSessionsBlocked()

            logger.debug('session_filter_blocked_session', {
                teamId,
                sessionId,
            })
        } finally {
            await this.redisPool.release(client)
        }
    }

    /**
     * Check if a session is blocked.
     *
     * @param teamId - The team ID
     * @param sessionId - The session ID
     * @returns true if the session is blocked, false otherwise
     */
    public async isBlocked(teamId: number, sessionId: string): Promise<boolean> {
        const key = this.generateKey(teamId, sessionId)

        // Check local cache first to avoid Redis round-trip
        const cached = this.localCache.get(key)
        if (cached !== undefined) {
            SessionBatchMetrics.incrementSessionFilterCacheHit()
            if (cached) {
                SessionBatchMetrics.incrementMessagesDroppedBlocked()
            }
            return cached
        }

        SessionBatchMetrics.incrementSessionFilterCacheMiss()

        const client = await this.redisPool.acquire()

        try {
            const exists = await client.exists(key)
            const isBlocked = exists === 1

            // Cache the result locally to prevent repeated Redis calls
            // Cache both blocked and not-blocked states
            this.localCache.set(key, isBlocked)

            if (isBlocked) {
                SessionBatchMetrics.incrementMessagesDroppedBlocked()
            }

            return isBlocked
        } finally {
            await this.redisPool.release(client)
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
                rateLimitEnabled: this.rateLimitEnabled,
            })
            SessionBatchMetrics.incrementNewSessionsRateLimited()

            if (this.rateLimitEnabled) {
                await this.blockSession(teamId, sessionId)
            }
        }
    }

    private generateKey(teamId: number, sessionId: string): string {
        return `${this.keyPrefix}:${teamId}:${sessionId}`
    }
}
