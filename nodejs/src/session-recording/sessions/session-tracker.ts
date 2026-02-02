import { LRUCache } from 'lru-cache'

import { RedisPool } from '../../types'
import { logger } from '../../utils/logger'
import { SESSION_TRACKER_REDIS_TTL_SECONDS } from '../constants'
import { SessionBatchMetrics } from './metrics'

const DEFAULT_LOCAL_CACHE_MAX_SIZE = 100_000

export class SessionTracker {
    private readonly keyPrefix = '@posthog/replay/session-seen'

    // In-memory cache to avoid hitting Redis for every message
    // Since Kafka partitions by session ID, the same session always hits the same consumer
    private readonly localCache: LRUCache<string, true>

    constructor(
        private readonly redisPool: RedisPool,
        localCacheTtlMs: number,
        localCacheMaxSize: number = DEFAULT_LOCAL_CACHE_MAX_SIZE
    ) {
        this.localCache = new LRUCache({
            max: localCacheMaxSize,
            ttl: localCacheTtlMs,
        })
    }

    /**
     * Check if session has been seen before, mark as seen if not.
     *
     * Fails open: if Redis is unavailable, assumes the session is not new
     * to avoid incorrectly triggering rate limits.
     *
     * @param teamId - The team ID
     * @param sessionId - The session ID
     * @returns true if this is a new session, false if already seen
     */
    public async trackSession(teamId: number, sessionId: string): Promise<boolean> {
        const key = this.generateKey(teamId, sessionId)

        // Check local cache first to avoid Redis round-trip
        if (this.localCache.has(key)) {
            SessionBatchMetrics.incrementSessionTrackerCacheHit()
            return false
        }

        SessionBatchMetrics.incrementSessionTrackerCacheMiss()

        let client
        try {
            client = await this.redisPool.acquire()

            // Use SET with NX (only set if not exists) and EX (expiry) for atomic check-and-set
            // Returns 'OK' if key was set (new session), null if already exists
            const wasSet = await client.set(key, '1', 'EX', SESSION_TRACKER_REDIS_TTL_SECONDS, 'NX')
            const isNewSession = wasSet === 'OK'

            // Cache the result locally regardless of whether it's new
            // This prevents repeated Redis calls for the same session
            this.localCache.set(key, true)

            if (isNewSession) {
                SessionBatchMetrics.incrementNewSessionsDetected()

                logger.debug('session_tracker_new_session', {
                    teamId,
                    sessionId,
                })
            }

            return isNewSession
        } catch (error) {
            // Fail open: if Redis is unavailable, assume not a new session
            logger.error('session_tracker_redis_error', {
                teamId,
                sessionId,
                error: String(error),
            })
            SessionBatchMetrics.incrementSessionTrackerRedisErrors()
            return false
        } finally {
            if (client) {
                await this.redisPool.release(client)
            }
        }
    }

    private generateKey(teamId: number, sessionId: string): string {
        return `${this.keyPrefix}:${teamId}:${sessionId}`
    }
}
