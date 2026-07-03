import { LRUCache } from 'lru-cache'

import { logger } from '~/common/utils/logger'
import { SESSION_TRACKER_REDIS_TTL_SECONDS } from '~/ingestion/pipelines/sessionreplay/constants'
import { SessionMap, SessionSet } from '~/ingestion/pipelines/sessionreplay/shared/session-map'
import { RedisPool } from '~/types'

import { SessionBatchMetrics } from './metrics'

const DEFAULT_LOCAL_CACHE_MAX_SIZE = 100_000

/**
 * Tracks which sessions have been seen before, so a session's first sighting can be treated as new
 * (rate-limited, key-generated) and later sightings as existing.
 *
 * The check ({@link hasSeen}) and the write ({@link markSeen}) are deliberately separate: the caller
 * marks a session seen only once it has durably generated the session's key. If they were fused (mark
 * on check, as an atomic SET NX), a failure between marking and key generation would leave a session
 * flagged seen but keyless — on retry it would resolve as existing and fetch a key that was never
 * generated. Keeping them apart lets a failed key generation leave the session unseen so the retry
 * regenerates.
 *
 * An in-memory LRU cache fronts Redis. Kafka partitions by session id, so the same session always
 * hits the same consumer, which makes the local cache effective and the split safe from cross-consumer
 * races.
 *
 * ## Failure policy
 *
 * The two methods degrade in opposite directions because they answer different questions, and the
 * pipeline holds two non-negotiable rules:
 *   1. Rate limiting is best-effort — on failure it may UNDER-count (let a session through un-limited)
 *      but must never OVER-count. Failing open is fine.
 *   2. Anything that could corrupt encryption — recording without a key (cleartext), or switching a
 *      session's key mid-stream — must FAIL HARD (throw and let the retry re-run), never guess.
 *
 * {@link hasSeen} answers "new or existing?", which the record path uses BOTH to rate-limit (rule 1)
 * AND to decide generate-vs-fetch of the encryption key (rule 2). Because a wrong answer there records
 * cleartext or switches keys, rule 2 wins: hasSeen fails hard. {@link markSeen} only persists the seen
 * flag; if it's lost the session is treated as new again next batch, but the key store is idempotent
 * (same key, no cleartext, no switch), so there's no integrity risk — it fails open under rule 1, with
 * the local cache masking the loss on this consumer.
 */
export class SessionTracker {
    private readonly keyPrefix = '@posthog/replay/session-seen'

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
     * Which of the given sessions have been seen before, without marking any. Pair with
     * {@link markSeen} after a session's key has been generated. Local-cache hits are answered without
     * Redis; the remaining sessions are checked in a single MGET.
     *
     * Fails hard: on a Redis error this throws so the caller's retry wrapper re-runs. hasSeen decides
     * whether a session generates a new key or fetches its existing one, so a wrong answer would record
     * cleartext (new session fetched as existing → no key) or switch a session's key mid-outage. Guessing
     * would corrupt encryption; halting until Redis recovers is the safe degradation. (Rate limiting can
     * tolerate a wrong answer — key integrity can't — so the stricter requirement wins here.)
     *
     * @returns a map keyed by `(teamId, sessionId)` — true if seen before, false if new
     */
    public async hasSeen(sessions: SessionSet): Promise<SessionMap<boolean>> {
        const result = new SessionMap<boolean>()
        const misses: { teamId: number; sessionId: string }[] = []
        for (const { teamId, sessionId } of sessions) {
            if (this.localCache.has(this.generateKey(teamId, sessionId))) {
                SessionBatchMetrics.incrementSessionTrackerCacheHit()
                result.set(teamId, sessionId, true)
            } else {
                SessionBatchMetrics.incrementSessionTrackerCacheMiss()
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
                const seen = values[i] !== null
                // Cache positives so repeated messages for a known session skip Redis. A negative isn't
                // cached: markSeen caches it once the session is actually recorded as seen.
                if (seen) {
                    this.localCache.set(this.generateKey(teamId, sessionId), true)
                }
                result.set(teamId, sessionId, seen)
            }
            return result
        } catch (error) {
            // Hard-fail: rethrow so the step's retry re-runs rather than guessing "seen" and risking a
            // keyless (cleartext) recording or a mid-session key switch.
            logger.error('session_tracker_has_seen_redis_error', { error: String(error) })
            SessionBatchMetrics.incrementSessionTrackerRedisErrors()
            throw error
        } finally {
            if (client) {
                await this.redisPool.release(client)
            }
            SessionBatchMetrics.observeSessionTrackerRedisLatency((performance.now() - startTime) / 1000)
        }
    }

    /**
     * Mark the given sessions as seen, in a single Redis pipeline. Call this only after each session's
     * key has been durably generated, so a failure before the key exists leaves the session unseen and
     * the retry regenerates.
     *
     * Fails open (rate-limiting rule 1 — see the class doc): if Redis is unavailable the marks aren't
     * persisted, but the local cache still records them for this consumer (the same session stays on this
     * consumer via partition affinity). A lost mark can only make the session look new again later, which
     * the idempotent key store handles without any cleartext/key-switch — so there's no integrity reason
     * to fail hard here, and doing so would needlessly halt on a fire-and-forget write.
     */
    public async markSeen(sessions: SessionSet): Promise<void> {
        if (sessions.size === 0) {
            return
        }

        const startTime = performance.now()
        let client
        try {
            client = await this.redisPool.acquire()
            const pipeline = client.pipeline()
            for (const { teamId, sessionId } of sessions) {
                const key = this.generateKey(teamId, sessionId)
                this.localCache.set(key, true)
                SessionBatchMetrics.incrementNewSessionsDetected()
                pipeline.set(key, '1', 'EX', SESSION_TRACKER_REDIS_TTL_SECONDS)
            }
            await pipeline.exec()
        } catch (error) {
            logger.error('session_tracker_mark_seen_redis_error', { error: String(error) })
            SessionBatchMetrics.incrementSessionTrackerRedisErrors()
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
