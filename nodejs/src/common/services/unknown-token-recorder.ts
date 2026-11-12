import { Counter } from 'prom-client'

import { type RedisV2 } from '~/common/redis/redis-v2'
import { logger } from '~/common/utils/logger'

/**
 * Sorted set of project tokens that resolved to no team, scored by the last time one was seen (epoch ms).
 * capture-logs has no Postgres access, so it reads this set to turn away tokens that belong to no team.
 */
export const UNKNOWN_TOKENS_KEY = 'capture_logs:unknown_tokens'

/** A token is written at most this often per process, so a steady 14/s of misses is a handful of writes. */
export const UNKNOWN_TOKEN_WRITE_DEBOUNCE_MS = 30_000
/** Entries older than this are trimmed. capture-logs only reads the last hour, so they carry no meaning. */
export const UNKNOWN_TOKEN_RETENTION_MS = 60 * 60 * 1000
const TRIM_INTERVAL_MS = 5 * 60 * 1000
/** Tokens are client input, so a flood of unique ones must not grow the set or this process without bound. */
export const UNKNOWN_TOKENS_MAX_ENTRIES = 100_000
const MAX_TOKEN_LENGTH = 200
const KEY_TTL_SECONDS = 2 * 60 * 60

export const unknownTokenWriteCounter = new Counter({
    name: 'logs_ingestion_unknown_token_write_total',
    help: 'Unknown project tokens written to the shared set that capture-logs reads, by outcome.',
    labelNames: ['outcome'],
})

/**
 * Records tokens for which the team lookup definitively found no team.
 * Call it only for a not-found result. A lookup that failed says nothing about the token, and recording it
 * would let a database blip turn a real token away at the edge.
 * Writes are fire-and-forget and swallow errors, so Redis can never fail or slow a batch.
 */
export class UnknownTokenRecorder {
    private readonly lastWrittenAt = new Map<string, number>()
    private lastTrimAt = 0

    constructor(
        private readonly redis: Pick<RedisV2, 'usePipeline'>,
        private readonly now: () => number = Date.now
    ) {}

    record(token: string): void {
        if (!token || token.length > MAX_TOKEN_LENGTH) {
            return
        }
        const now = this.now()
        const last = this.lastWrittenAt.get(token)
        if (last !== undefined && now - last < UNKNOWN_TOKEN_WRITE_DEBOUNCE_MS) {
            unknownTokenWriteCounter.inc({ outcome: 'debounced' })
            return
        }
        if (this.lastWrittenAt.size >= UNKNOWN_TOKENS_MAX_ENTRIES) {
            this.evictExpired(now)
            if (this.lastWrittenAt.size >= UNKNOWN_TOKENS_MAX_ENTRIES) {
                unknownTokenWriteCounter.inc({ outcome: 'dropped_full' })
                return
            }
        }
        // Set before the write starts, so concurrent misses for one token share a single write.
        this.lastWrittenAt.set(token, now)
        const trim = now - this.lastTrimAt >= TRIM_INTERVAL_MS
        if (trim) {
            this.lastTrimAt = now
        }
        void this.write(token, now, trim)
    }

    private evictExpired(now: number): void {
        for (const [token, at] of this.lastWrittenAt) {
            if (now - at >= UNKNOWN_TOKEN_WRITE_DEBOUNCE_MS) {
                this.lastWrittenAt.delete(token)
            }
        }
    }

    private async write(token: string, now: number, trim: boolean): Promise<void> {
        try {
            const results = await this.redis.usePipeline({ name: 'unknown-token-record', failOpen: true }, (p) => {
                p.zadd(UNKNOWN_TOKENS_KEY, now, token)
                p.expire(UNKNOWN_TOKENS_KEY, KEY_TTL_SECONDS)
                if (trim) {
                    p.zremrangebyscore(UNKNOWN_TOKENS_KEY, '-inf', now - UNKNOWN_TOKEN_RETENTION_MS)
                    p.zremrangebyrank(UNKNOWN_TOKENS_KEY, 0, -(UNKNOWN_TOKENS_MAX_ENTRIES + 1))
                }
            })
            const failed = results === null || results.some(([err]) => err !== null)
            unknownTokenWriteCounter.inc({ outcome: failed ? 'error' : 'written' })
        } catch (error) {
            unknownTokenWriteCounter.inc({ outcome: 'error' })
            logger.warn('unknown_token_record_failed', { error: String(error) })
        }
    }
}
