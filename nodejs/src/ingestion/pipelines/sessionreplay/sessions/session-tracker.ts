import { LRUCache } from 'lru-cache'

import { logger } from '~/common/utils/logger'
import { SESSION_TRACKER_REDIS_TTL_SECONDS } from '~/ingestion/pipelines/sessionreplay/constants'
import { SessionMap, SessionSet } from '~/ingestion/pipelines/sessionreplay/shared/session-map'
import { RedisPool } from '~/types'

import { SessionBatchMetrics } from './metrics'

const DEFAULT_LOCAL_CACHE_MAX_SIZE = 100_000

// Any value in a seen key means seen. Code that billed a session when it first saw it wrote '1' to the seen key,
// so a session with that value counts as billed.
const SEEN = 'seen'
const BILLED_AT_FIRST_SIGHT = '1'
// The billed key holds the time, in milliseconds, that every usage record for the session carries. The usage table
// removes a duplicate record only within one UTC day, so one stored time lets it remove every resend of the session.
// The prefix marks a session whose record reached the usage service. The billed key is separate from the seen key
// because billing must not change how long a session stays seen. The seen state decides whether a session gets a new
// encryption key or reads its existing one.
const BILLED_PREFIX = 'billed:'

export interface BillingClaim {
    teamId: number
    sessionId: string
    /** The time to store when the session has no stored time. */
    timestampMs: number
    ttlSeconds: number
}

export interface BilledSession {
    teamId: number
    sessionId: string
    timestampMs: number
    ttlSeconds: number
}

type PipelineResults = [Error | null, unknown][] | null

function pipelineValues(results: PipelineResults, count: number): unknown[] {
    if (!results || results.length !== count) {
        throw new Error('Redis pipeline returned an incomplete result')
    }
    return results.map(([error, value]) => {
        if (error) {
            throw error
        }
        return value
    })
}

function storedBillingTime(value: unknown): number | undefined {
    const timestampMs = typeof value === 'string' ? Number(value) : NaN
    return Number.isSafeInteger(timestampMs) && timestampMs > 0 ? timestampMs : undefined
}

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
    private readonly keyPrefix: string

    private readonly billedKeyPrefix: string

    private readonly localCache: LRUCache<string, true>

    private readonly billedCache: LRUCache<string, true>

    /**
     * @param keyNamespace - Optional Redis key namespace. Omit (the default) for the main lane — this
     *   keeps the key prefix exactly `@posthog/replay/session-seen` so existing sessions aren't seen as
     *   new. A secondary pipeline (e.g. the ML mirror) MUST pass its own namespace so it doesn't share
     *   seen-state with the main lane; otherwise it can mark a session seen without the main lane's key
     *   and cause a cleartext recording there.
     */
    constructor(
        private readonly redisPool: RedisPool,
        localCacheTtlMs: number,
        localCacheMaxSize: number = DEFAULT_LOCAL_CACHE_MAX_SIZE,
        keyNamespace?: string
    ) {
        const namespacePrefix = keyNamespace ? `@posthog/replay/${keyNamespace}` : '@posthog/replay'
        this.keyPrefix = `${namespacePrefix}/session-seen`
        this.billedKeyPrefix = `${namespacePrefix}/session-billed`
        this.localCache = new LRUCache({
            max: localCacheMaxSize,
            ttl: localCacheTtlMs,
        })
        this.billedCache = new LRUCache({
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
                // NX keeps a '1' that code billing at first sight wrote after this consumer's hasSeen read. The key
                // normally does not exist here, because only sessions that read as new reach this write.
                pipeline.set(key, SEEN, 'EX', SESSION_TRACKER_REDIS_TTL_SECONDS, 'NX')
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

    /**
     * Returns the billing time of each session that has not billed. The first call for a session stores its
     * candidate time, and every later call, on any consumer, returns the stored time.
     * A session without a billed mark counts as unbilled, because a mark that failed to persist must not stop the bill.
     * On a Redis error every session outside the local billed cache counts as unbilled, with its candidate time. A
     * session saved in only one flush has no later flush to bill it. The usage table removes a resend only when both
     * records fall on the same UTC day.
     */
    public async claimBillingTimes(claims: BillingClaim[]): Promise<SessionMap<number>> {
        const unbilled = new SessionMap<number>()
        const misses = claims.filter(
            ({ teamId, sessionId }) => !this.billedCache.has(this.generateBilledKey(teamId, sessionId))
        )

        if (misses.length === 0) {
            return unbilled
        }

        // Sessions that code billing at first sight already billed. They get a billed mark, so a late upload does
        // not bill them again after their seen key expires.
        const billedAtFirstSight: BilledSession[] = []
        const startTime = performance.now()
        let client
        try {
            client = await this.redisPool.acquire()
            const pipeline = client.pipeline()
            for (const { teamId, sessionId, timestampMs, ttlSeconds } of misses) {
                const billedKey = this.generateBilledKey(teamId, sessionId)
                pipeline.set(billedKey, String(timestampMs), 'EX', ttlSeconds, 'NX')
                pipeline.get(billedKey)
                pipeline.get(this.generateKey(teamId, sessionId))
            }
            const values = pipelineValues(await pipeline.exec(), misses.length * 3)
            for (let i = 0; i < misses.length; i++) {
                const { teamId, sessionId, timestampMs, ttlSeconds } = misses[i]
                const [billedValue, seenValue] = [values[3 * i + 1], values[3 * i + 2]]
                if (typeof billedValue === 'string' && billedValue.startsWith(BILLED_PREFIX)) {
                    this.billedCache.set(this.generateBilledKey(teamId, sessionId), true)
                } else if (seenValue === BILLED_AT_FIRST_SIGHT) {
                    const storedTimestampMs = storedBillingTime(billedValue) ?? timestampMs
                    billedAtFirstSight.push({ teamId, sessionId, timestampMs: storedTimestampMs, ttlSeconds })
                } else {
                    unbilled.set(teamId, sessionId, storedBillingTime(billedValue) ?? timestampMs)
                }
            }
        } catch (error) {
            logger.error('session_tracker_claim_billing_times_redis_error', { error: String(error) })
            SessionBatchMetrics.incrementSessionTrackerRedisErrors()
            for (const { teamId, sessionId, timestampMs } of misses) {
                unbilled.set(teamId, sessionId, timestampMs)
            }
            return unbilled
        } finally {
            if (client) {
                await this.redisPool.release(client)
            }
            SessionBatchMetrics.observeSessionTrackerRedisLatency((performance.now() - startTime) / 1000)
        }

        await this.markBilled(billedAtFirstSight)
        return unbilled
    }

    /**
     * Call only after the sessions' usage records reached the usage service. Fails open, like {@link markSeen}. The
     * local cache keeps the mark when the Redis write fails, so a Redis failure does not resend the session on every
     * flush. A later resend carries the billing time that Redis stored, and the usage table removes it.
     */
    public async markBilled(sessions: BilledSession[]): Promise<void> {
        if (sessions.length === 0) {
            return
        }

        const startTime = performance.now()
        let client
        try {
            client = await this.redisPool.acquire()
            const pipeline = client.pipeline()
            for (const { teamId, sessionId, timestampMs, ttlSeconds } of sessions) {
                const key = this.generateBilledKey(teamId, sessionId)
                this.billedCache.set(key, true)
                pipeline.set(key, `${BILLED_PREFIX}${timestampMs}`, 'EX', ttlSeconds)
            }
            pipelineValues(await pipeline.exec(), sessions.length)
        } catch (error) {
            logger.error('session_tracker_mark_billed_redis_error', { error: String(error) })
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

    private generateBilledKey(teamId: number, sessionId: string): string {
        return `${this.billedKeyPrefix}:${teamId}:${sessionId}`
    }
}
