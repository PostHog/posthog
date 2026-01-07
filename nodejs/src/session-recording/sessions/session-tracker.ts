import { LRUCache } from 'lru-cache'

import { RedisPool } from '../../types'
import { logger } from '../../utils/logger'
import { SessionBatchMetrics } from './metrics'

const DEFAULT_LOCAL_CACHE_TTL_MS = 5 * 60 * 1000 // 5 minutes
const DEFAULT_LOCAL_CACHE_MAX_SIZE = 100_000

export class SessionTracker {
    private readonly keyPrefix = '@posthog/replay/session-seen'
    private readonly ttlSeconds = 48 * 60 * 60 // 48 hours

    // In-memory cache to avoid hitting Redis for every message
    // Since Kafka partitions by session ID, the same session always hits the same consumer
    private readonly localCache: LRUCache<string, true>

    constructor(
        private readonly redisPool: RedisPool,
        localCacheTtlMs: number = DEFAULT_LOCAL_CACHE_TTL_MS,
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

        const client = await this.redisPool.acquire()

        try {
            // Use SET with NX (only set if not exists) and EX (expiry) for atomic check-and-set
            // Returns 'OK' if key was set (new session), null if already exists
            const wasSet = await client.set(key, '1', 'EX', this.ttlSeconds, 'NX')
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
        } finally {
            await this.redisPool.release(client)
        }
    }

    private generateKey(teamId: number, sessionId: string): string {
        return `${this.keyPrefix}:${teamId}:${sessionId}`
    }
}
