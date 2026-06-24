import { LRUCache } from 'lru-cache'

import { SESSION_TRACKER_REDIS_TTL_SECONDS } from '~/ingestion/pipelines/sessionreplay/constants'
import { RedisPool } from '~/types'
import { logger } from '~/utils/logger'

import { SessionBatchMetrics } from './metrics'

const DEFAULT_LOCAL_CACHE_MAX_SIZE = 100_000
const DEFAULT_REDIS_TIMEOUT_MS = 5000

export class SessionTracker {
    private readonly keyPrefix = '@posthog/replay/session-seen'

    // In-memory cache to avoid hitting Redis for every message
    // Since Kafka partitions by session ID, the same session always hits the same consumer
    private readonly localCache: LRUCache<string, true>

    constructor(
        private readonly redisPool: RedisPool,
        localCacheTtlMs: number,
        localCacheMaxSize: number = DEFAULT_LOCAL_CACHE_MAX_SIZE,
        private readonly redisTimeoutMs: number = DEFAULT_REDIS_TIMEOUT_MS
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

        const startTime = performance.now()
        let client
        try {
            const redisOp = async () => {
                client = await this.redisPool.acquire()
                return client.set(key, '1', 'EX', SESSION_TRACKER_REDIS_TTL_SECONDS, 'NX')
            }
            const timeout = new Promise<never>((_, reject) =>
                setTimeout(() => reject(new Error(`Redis timeout after ${this.redisTimeoutMs}ms`)), this.redisTimeoutMs)
            )

            const wasSet = await Promise.race([redisOp(), timeout])
            const isNewSession = wasSet === 'OK'

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
            // Fail open: if Redis is unavailable or times out, assume not a new session
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
            SessionBatchMetrics.observeSessionTrackerRedisLatency((performance.now() - startTime) / 1000)
        }
    }

    private generateKey(teamId: number, sessionId: string): string {
        return `${this.keyPrefix}:${teamId}:${sessionId}`
    }
}
