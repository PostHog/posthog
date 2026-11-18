import { Counter } from 'prom-client'

import { type RedisV2 } from '~/common/redis/redis-v2'
import { logger } from '~/common/utils/logger'

/**
 * Sorted set of project tokens that resolved to no team, scored by the last time one was seen (epoch ms).
 * capture-logs has no Postgres access, so it reads this set to turn away tokens that belong to no team.
 */
export const UNKNOWN_TOKENS_KEY = 'capture_logs:unknown_tokens'

/**
 * A token is written only once it has kept missing for this long. The team lookup reads a replica and caches a
 * miss for up to 2.5 minutes, so a project created a moment ago can miss once. Waiting past that cache means the
 * miss that triggers the write came from a fresh lookup, and a new project's token is never turned away.
 */
export const UNKNOWN_TOKEN_CONFIRM_MS = 3 * 60 * 1000
/** A confirmed token is written at most this often per process, so a steady 14/s of misses is a handful of writes. */
export const UNKNOWN_TOKEN_WRITE_DEBOUNCE_MS = 30_000
/** A token not missed for this long is forgotten, and its confirmation starts over. */
export const UNKNOWN_TOKEN_IDLE_MS = 10 * 60 * 1000
/** Entries older than this are trimmed. capture-logs only reads the last hour, so they carry no meaning. */
export const UNKNOWN_TOKEN_RETENTION_MS = 60 * 60 * 1000
/** Tokens are client input, so a flood of unique ones must not grow the set or this process without bound. */
export const UNKNOWN_TOKENS_MAX_ENTRIES = 100_000
/** A Redis that stops answering must not pile up pending writes. */
export const UNKNOWN_TOKEN_MAX_IN_FLIGHT_WRITES = 20
const WRITE_DEADLINE_MS = 1000
const MAX_TOKEN_LENGTH = 200
const KEY_TTL_SECONDS = 2 * 60 * 60

export const unknownTokenWriteCounter = new Counter({
    name: 'logs_ingestion_unknown_token_write_total',
    help: 'Unknown project tokens written to the shared set that capture-logs reads, by outcome.',
    labelNames: ['outcome'],
})

type TokenState = {
    firstMissAt: number
    lastMissAt: number
    writtenAt?: number
}

/**
 * Records tokens for which the team lookup definitively found no team.
 * Call it only for a not-found result. A lookup that failed says nothing about the token, and recording it
 * would let a database blip turn a real token away at the edge.
 * Writes are fire-and-forget and swallow errors, so Redis can never fail or slow a batch.
 */
export class UnknownTokenRecorder {
    // Kept in order of last miss, so idle entries are always at the front.
    private readonly tokens = new Map<string, TokenState>()
    private inFlightWrites = 0

    constructor(
        private readonly redis: Pick<RedisV2, 'usePipeline'>,
        private readonly now: () => number = Date.now
    ) {}

    record(token: string): void {
        if (!token || token.length > MAX_TOKEN_LENGTH) {
            return
        }
        const now = this.now()
        this.evictIdle(now)

        let state = this.tokens.get(token)
        if (state === undefined) {
            if (this.tokens.size >= UNKNOWN_TOKENS_MAX_ENTRIES) {
                unknownTokenWriteCounter.inc({ outcome: 'dropped_full' })
                return
            }
            state = { firstMissAt: now, lastMissAt: now }
        }
        // Re-inserting moves the token to the back, which keeps the map in order of last miss.
        this.tokens.delete(token)
        state.lastMissAt = now
        this.tokens.set(token, state)

        if (now - state.firstMissAt < UNKNOWN_TOKEN_CONFIRM_MS) {
            unknownTokenWriteCounter.inc({ outcome: 'unconfirmed' })
            return
        }
        if (state.writtenAt !== undefined && now - state.writtenAt < UNKNOWN_TOKEN_WRITE_DEBOUNCE_MS) {
            unknownTokenWriteCounter.inc({ outcome: 'debounced' })
            return
        }
        if (this.inFlightWrites >= UNKNOWN_TOKEN_MAX_IN_FLIGHT_WRITES) {
            unknownTokenWriteCounter.inc({ outcome: 'dropped_busy' })
            return
        }
        // Set before the write starts, so concurrent misses for one token share a single write.
        state.writtenAt = now
        void this.write(token, now)
    }

    private evictIdle(now: number): void {
        for (const [token, state] of this.tokens) {
            if (now - state.lastMissAt < UNKNOWN_TOKEN_IDLE_MS) {
                return
            }
            this.tokens.delete(token)
        }
    }

    private async write(token: string, now: number): Promise<void> {
        this.inFlightWrites++
        try {
            const results = await this.redis.usePipeline(
                { name: 'unknown-token-record', failOpen: true, deadlineMs: WRITE_DEADLINE_MS },
                (p) => {
                    p.zadd(UNKNOWN_TOKENS_KEY, now, token)
                    p.expire(UNKNOWN_TOKENS_KEY, KEY_TTL_SECONDS)
                    // Both trims cost O(log N) when nothing is removed, so every write keeps the set within its cap.
                    p.zremrangebyscore(UNKNOWN_TOKENS_KEY, '-inf', now - UNKNOWN_TOKEN_RETENTION_MS)
                    p.zremrangebyrank(UNKNOWN_TOKENS_KEY, 0, -(UNKNOWN_TOKENS_MAX_ENTRIES + 1))
                }
            )
            const failed = results === null || results.some(([err]) => err !== null)
            unknownTokenWriteCounter.inc({ outcome: failed ? 'error' : 'written' })
        } catch (error) {
            unknownTokenWriteCounter.inc({ outcome: 'error' })
            logger.warn('unknown_token_record_failed', { error: String(error) })
        } finally {
            this.inFlightWrites--
        }
    }
}
