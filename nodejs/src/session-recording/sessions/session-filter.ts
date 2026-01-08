import { LRUCache } from 'lru-cache'

import { RedisPool } from '../../types'
import { logger } from '../../utils/logger'
import { SESSION_FILTER_REDIS_TTL_SECONDS } from '../constants'
import { SessionBatchMetrics } from './metrics'

const DEFAULT_LOCAL_CACHE_MAX_SIZE = 100_000

/**
 * Manages a blocklist of sessions that should be dropped.
 *
 * When a session is rate-limited on its first message, we block the entire session
 * to prevent half-ingested recordings. The blocklist is persisted in Redis with
 * an in-memory LRU cache to minimize Redis round-trips.
 */
export class SessionFilter {
    private readonly keyPrefix = '@posthog/replay/session-blocked'

    // In-memory cache to avoid hitting Redis for every message
    // Since Kafka partitions by session ID, the same session always hits the same consumer
    // Maps key -> blocked status (true = blocked, false = not blocked but checked)
    private readonly localCache: LRUCache<string, boolean>

    constructor(
        private readonly redisPool: RedisPool,
        private readonly localCacheTtlMs: number,
        localCacheMaxSize: number = DEFAULT_LOCAL_CACHE_MAX_SIZE
    ) {
        this.localCache = new LRUCache({
            max: localCacheMaxSize,
            ttl: localCacheTtlMs,
        })
    }

    /**
     * Block a session so all future messages are dropped.
     *
     * @param teamId - The team ID
     * @param sessionId - The session ID to block
     */
    public async blockSession(teamId: number, sessionId: string): Promise<void> {
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

    private generateKey(teamId: number, sessionId: string): string {
        return `${this.keyPrefix}:${teamId}:${sessionId}`
    }
}
