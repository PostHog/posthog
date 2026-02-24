import { createHash } from 'crypto'

import { RedisV2 } from '../redis/redis-v2'

// Branded type — callers must use idempotencyKey() to construct, can't pass raw strings
export type IdempotencyKey = string & { readonly __brand: 'IdempotencyKey' }

export function idempotencyKey(...parts: string[]): IdempotencyKey {
    const hash = createHash('sha256').update(parts.join(':')).digest('hex').slice(0, 32)
    return hash as IdempotencyKey
}

export enum IdempotencyState {
    /** We claimed it — proceed with processing */
    New = 'new',
    /** Already exists but not acked — caller decides what to do */
    Existing = 'existing',
    /** Definitely processed — safe to skip */
    Acked = 'acked',
}

// Scores below this threshold are claimed (score = unix timestamp in ms).
// Scores at or above are acked (score = timestamp + offset).
// This keeps acked entries at the top of the ZSET so they survive eviction longest.
// Current ms timestamps are ~1.7e12, so 1e16 is safely above any real timestamp.
const ACKED_SCORE_OFFSET = 1e16

const BASE_REDIS_KEY = process.env.NODE_ENV === 'test' ? '@posthog-test/idempotency' : '@posthog/idempotency'

export interface IdempotencyServiceConfig {
    maxSize: number
    /** TTL on the ZSET key itself as a safety net — refreshed on every operation (default 86400s / 24h) */
    keyTtlSeconds?: number
}

export class IdempotencyService {
    private readonly maxSize: number
    private readonly keyTtlSeconds: number

    constructor(
        private redis: RedisV2,
        config: IdempotencyServiceConfig
    ) {
        this.maxSize = config.maxSize
        this.keyTtlSeconds = config.keyTtlSeconds ?? 86400
    }

    private redisKey(namespace: string): string {
        return `${BASE_REDIS_KEY}:${namespace}`
    }

    async claim(namespace: string, key: IdempotencyKey): Promise<IdempotencyState | null> {
        const result = await this.claimBatch([[namespace, key]])
        return result?.get(key) ?? null
    }

    async ack(namespace: string, key: IdempotencyKey): Promise<void> {
        await this.ackBatch([[namespace, key]])
    }

    async release(namespace: string, key: IdempotencyKey): Promise<void> {
        await this.releaseBatch([[namespace, key]])
    }

    async claimBatch(
        entries: [namespace: string, key: IdempotencyKey][]
    ): Promise<Map<IdempotencyKey, IdempotencyState> | null> {
        if (entries.length === 0) {
            return new Map()
        }

        const now = Date.now()

        // Pipeline 1: attempt claim (ZADD NX) + check state (ZSCORE) for each entry, then trim + expire per namespace
        const namespacesUsed = new Set<string>()
        const results = await this.redis.usePipeline({ name: 'idempotency-claim', failOpen: true }, (pipeline) => {
            for (const [namespace, key] of entries) {
                const zsetKey = this.redisKey(namespace)
                pipeline.zadd(zsetKey, 'NX', now, key)
                pipeline.zscore(zsetKey, key)
                namespacesUsed.add(namespace)
            }
            for (const namespace of namespacesUsed) {
                const zsetKey = this.redisKey(namespace)
                pipeline.zremrangebyrank(zsetKey, 0, -(this.maxSize + 1))
                pipeline.expire(zsetKey, this.keyTtlSeconds)
            }
        })

        if (!results) {
            return null
        }

        const states = new Map<IdempotencyKey, IdempotencyState>()
        const toTouch: [string, IdempotencyKey][] = []

        for (let i = 0; i < entries.length; i++) {
            const [namespace, key] = entries[i]
            const [, zaddResult] = results[i * 2]
            const [, scoreResult] = results[i * 2 + 1]

            if (zaddResult === 1) {
                states.set(key, IdempotencyState.New)
            } else {
                const score = scoreResult !== null ? parseFloat(scoreResult) : 0
                if (score >= ACKED_SCORE_OFFSET) {
                    states.set(key, IdempotencyState.Acked)
                } else {
                    states.set(key, IdempotencyState.Existing)
                    toTouch.push([namespace, key])
                }
            }
        }

        // Pipeline 2: touch existing non-acked entries to refresh their LRU position
        if (toTouch.length > 0) {
            await this.redis.usePipeline({ name: 'idempotency-touch', failOpen: true }, (pipeline) => {
                for (const [namespace, key] of toTouch) {
                    pipeline.zadd(this.redisKey(namespace), 'XX', now, key)
                }
            })
        }

        return states
    }

    async ackBatch(entries: [namespace: string, key: IdempotencyKey][]): Promise<void> {
        if (entries.length === 0) {
            return
        }

        const now = Date.now()
        const ackScore = now + ACKED_SCORE_OFFSET

        await this.redis.usePipeline({ name: 'idempotency-ack', failOpen: true }, (pipeline) => {
            const namespacesUsed = new Set<string>()
            for (const [namespace, key] of entries) {
                pipeline.zadd(this.redisKey(namespace), 'XX', ackScore, key)
                namespacesUsed.add(namespace)
            }
            for (const namespace of namespacesUsed) {
                pipeline.expire(this.redisKey(namespace), this.keyTtlSeconds)
            }
        })
    }

    async releaseBatch(entries: [namespace: string, key: IdempotencyKey][]): Promise<void> {
        if (entries.length === 0) {
            return
        }

        await this.redis.usePipeline({ name: 'idempotency-release', failOpen: true }, (pipeline) => {
            for (const [namespace, key] of entries) {
                pipeline.zrem(this.redisKey(namespace), key)
            }
        })
    }
}
