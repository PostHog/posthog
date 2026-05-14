import { Counter } from 'prom-client'

import { RedisV2, getRedisPipelineResults } from '~/common/redis/redis-v2'

const requestsTotal = new Counter({
    name: 'keyed_rate_limiter_requests_total',
    help: 'Per-input rate-limit decisions, labelled by outcome.',
    labelNames: ['name', 'method', 'outcome'],
})
const redisCallsTotal = new Counter({
    name: 'keyed_rate_limiter_redis_calls_total',
    help: 'Lua script dispatches. requests/redis_calls = grouping ratio.',
    labelNames: ['name', 'method'],
})

/**
 * Token-bucket rate limiter keyed by an arbitrary string id, backed by Redis.
 * Multiple limiters can share a Redis via different `name` prefixes.
 */
export interface KeyedRateLimiterConfig {
    /** Logical name; produces `@posthog/<name>/tokens/<id>` keys (`@posthog-test/...` under NODE_ENV=test). */
    name: string
    /** Default bucket params; per-request overrides take precedence. */
    bucketSize?: number
    refillRate?: number
    ttlSeconds?: number
}

export interface KeyedRateLimitRequest {
    id: string
    cost: number
    bucketSize?: number
    refillRate?: number
    ttlSeconds?: number
}

export type KeyedRateLimit = {
    tokens: number
    isRateLimited: boolean
}

const buildKeyPrefix = (name: string): string => {
    const root = process.env.NODE_ENV === 'test' ? '@posthog-test' : '@posthog'
    return `${root}/${name}/tokens`
}

export class KeyedRateLimiterService {
    private readonly keyPrefix: string

    constructor(
        private readonly config: KeyedRateLimiterConfig,
        private readonly redis: RedisV2
    ) {
        this.keyPrefix = buildKeyPrefix(config.name)
    }

    public getKeyPrefix(): string {
        return this.keyPrefix
    }

    private rateLimitArgs(req: KeyedRateLimitRequest): [string, number, number, number, number, number] {
        const nowSeconds = Math.round(Date.now() / 1000)
        const bucketSize = req.bucketSize ?? this.config.bucketSize
        const refillRate = req.refillRate ?? this.config.refillRate
        const ttlSeconds = req.ttlSeconds ?? this.config.ttlSeconds
        if (bucketSize == null || refillRate == null || ttlSeconds == null) {
            throw new Error(
                `KeyedRateLimiterService(${this.config.name}): missing bucketSize/refillRate/ttlSeconds for ${req.id}`
            )
        }
        return [`${this.keyPrefix}/${req.id}`, nowSeconds, req.cost, bucketSize, refillRate, ttlSeconds]
    }

    public async rateLimitMany(requests: KeyedRateLimitRequest[]): Promise<[string, KeyedRateLimit][]> {
        if (requests.length === 0) {
            return []
        }

        const bucketSizes = requests.map((req) => {
            const bucketSize = req.bucketSize ?? this.config.bucketSize
            if (bucketSize == null) {
                throw new Error(`KeyedRateLimiterService(${this.config.name}): missing bucketSize for ${req.id}`)
            }
            return bucketSize
        })

        const res = await this.redis.usePipeline(
            { name: `keyed-rate-limiter:${this.config.name}`, failOpen: true },
            (pipeline) => {
                requests.forEach((req) => {
                    pipeline.checkRateLimitV2(...this.rateLimitArgs(req))
                })
            }
        )

        redisCallsTotal.inc({ name: this.config.name, method: 'rateLimitMany' }, requests.length)

        if (!res) {
            // failOpen — Redis blipped; allow everything rather than dropping ingestion.
            requestsTotal.inc({ name: this.config.name, method: 'rateLimitMany', outcome: 'allowed' }, requests.length)
            return requests.map((req, i) => [req.id, { tokens: bucketSizes[i], isRateLimited: false }])
        }

        let allowed = 0
        let limited = 0
        const out: [string, KeyedRateLimit][] = requests.map((req, index) => {
            const [tokenRes] = getRedisPipelineResults(res, index, 1)
            const tokensAfter = tokenRes[1]?.[1] ?? bucketSizes[index]
            const isRateLimited = Number(tokensAfter) <= 0
            if (isRateLimited) {
                limited++
            } else {
                allowed++
            }
            return [req.id, { tokens: Number(tokensAfter), isRateLimited }]
        })
        if (allowed > 0) {
            requestsTotal.inc({ name: this.config.name, method: 'rateLimitMany', outcome: 'allowed' }, allowed)
        }
        if (limited > 0) {
            requestsTotal.inc({ name: this.config.name, method: 'rateLimitMany', outcome: 'limited' }, limited)
        }
        return out
    }

    /**
     * Coalesced variant of rateLimitMany. Same input/output shape, but N inputs
     * across M unique ids dispatch only M Redis calls — per-input decisions are
     * fanned out client-side from each id's `tokensBefore`. For uniform-cost
     * batches the per-input decisions match rateLimitMany exactly.
     *
     * Uses the V3 lua script (HMGET + multi-field HSET + conditional EXPIRE).
     * Per-id bucket params come from the first request seen for that id.
     */
    public async rateLimitGrouped(requests: KeyedRateLimitRequest[]): Promise<[string, KeyedRateLimit][]> {
        if (requests.length === 0) {
            return []
        }

        const grouped = new Map<string, KeyedRateLimitRequest>()
        for (const req of requests) {
            const existing = grouped.get(req.id)
            if (existing) {
                existing.cost += req.cost
            } else {
                grouped.set(req.id, { ...req })
            }
        }

        const items = [...grouped.values()]
        const bucketSizes = items.map((req) => {
            const bucketSize = req.bucketSize ?? this.config.bucketSize
            if (bucketSize == null) {
                throw new Error(`KeyedRateLimiterService(${this.config.name}): missing bucketSize for ${req.id}`)
            }
            return bucketSize
        })

        const res = await this.redis.usePipeline(
            { name: `keyed-rate-limiter-grouped:${this.config.name}`, failOpen: true },
            (pipeline) => {
                items.forEach((req) => {
                    pipeline.checkRateLimitV3(...this.rateLimitArgs(req))
                })
            }
        )

        redisCallsTotal.inc({ name: this.config.name, method: 'rateLimitGrouped' }, items.length)

        const budgetById = new Map<string, number>()
        items.forEach((req, index) => {
            if (res) {
                const [tokenRes] = getRedisPipelineResults(res, index, 1)
                const tokensBefore = tokenRes[1]?.[0]
                budgetById.set(req.id, tokensBefore != null ? Number(tokensBefore) : bucketSizes[index])
            } else {
                budgetById.set(req.id, bucketSizes[index])
            }
        })

        let allowed = 0
        let limited = 0
        const out: [string, KeyedRateLimit][] = requests.map((req) => {
            const remaining = budgetById.get(req.id) ?? 0
            if (remaining >= req.cost) {
                const next = remaining - req.cost
                budgetById.set(req.id, next)
                const isRateLimited = next <= 0
                if (isRateLimited) {
                    limited++
                } else {
                    allowed++
                }
                return [req.id, { tokens: next, isRateLimited }]
            }
            limited++
            return [req.id, { tokens: -1, isRateLimited: true }]
        })
        if (allowed > 0) {
            requestsTotal.inc({ name: this.config.name, method: 'rateLimitGrouped', outcome: 'allowed' }, allowed)
        }
        if (limited > 0) {
            requestsTotal.inc({ name: this.config.name, method: 'rateLimitGrouped', outcome: 'limited' }, limited)
        }
        return out
    }
}
