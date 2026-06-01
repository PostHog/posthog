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
    /** When false, throw if the Redis pipeline returns null instead of fail-open allowing all. Default: true (fail open). */
    failOpen?: boolean
}

export interface KeyedRateLimitRequest {
    id: string
    cost: number
    bucketSize?: number
    refillRate?: number
    ttlSeconds?: number
    /** Override the request timestamp (seconds). Default: `Math.round(Date.now() / 1000)`. Used for lag-aware rate limiting where the timestamp comes from message headers. */
    now?: number
}

export type KeyedRateLimit = {
    /** Pre-deduction token count — uncapped accrued credit (PR 57920 contract). */
    tokensBefore: number
    /** Post-deduction token count. -1 when the cost exceeded the available budget. */
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
        const nowSeconds = req.now ?? Math.round(Date.now() / 1000)
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
            if (this.config.failOpen === false) {
                throw new Error(`KeyedRateLimiterService(${this.config.name}): rate-limit pipeline failed`)
            }
            requestsTotal.inc({ name: this.config.name, method: 'rateLimitMany', outcome: 'allowed' }, requests.length)
            return requests.map((req, i) => [
                req.id,
                { tokensBefore: bucketSizes[i], tokens: bucketSizes[i], isRateLimited: false },
            ])
        }

        let allowed = 0
        let limited = 0
        const out: [string, KeyedRateLimit][] = requests.map((req, index) => {
            const [tokenRes] = getRedisPipelineResults(res, index, 1)
            const tokensBefore = Number(tokenRes[1]?.[0] ?? bucketSizes[index])
            const tokensAfter = Number(tokenRes[1]?.[1] ?? bucketSizes[index])
            const isRateLimited = tokensAfter <= 0
            if (isRateLimited) {
                limited++
            } else {
                allowed++
            }
            return [req.id, { tokensBefore, tokens: tokensAfter, isRateLimited }]
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
     * Coalesced variant of rateLimitMany — N inputs across M unique ids → M Redis calls.
     * Per-input decisions fan out client-side from each id's `tokensBefore`.
     *
     * Boundary differs from rateLimitMany: an input whose cost lands exactly on
     * the local budget (`next === 0`) is allowed here, rate-limited there. Per-id
     * bucket params come from the first request seen for that id.
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

        if (!res) {
            if (this.config.failOpen === false) {
                throw new Error(`KeyedRateLimiterService(${this.config.name}): rate-limit pipeline failed`)
            }
            // Fail-open: allow every request, no fan-out deduction. The earlier shape
            // here seeded `budgetById` with bucketSize and then ran the fan-out, which
            // wrongly rate-limited any id whose total cost exceeded bucketSize.
            const bucketSizeById = new Map(items.map((req, i) => [req.id, bucketSizes[i]]))
            requestsTotal.inc(
                { name: this.config.name, method: 'rateLimitGrouped', outcome: 'allowed' },
                requests.length
            )
            return requests.map((req) => {
                const bucketSize = bucketSizeById.get(req.id) ?? 0
                return [req.id, { tokensBefore: bucketSize, tokens: bucketSize, isRateLimited: false }]
            })
        }

        const budgetById = new Map<string, number>()
        items.forEach((req, index) => {
            const [tokenRes] = getRedisPipelineResults(res, index, 1)
            const tokensBefore = tokenRes[1]?.[0]
            budgetById.set(req.id, tokensBefore != null ? Number(tokensBefore) : bucketSizes[index])
        })

        let allowed = 0
        let limited = 0
        const out: [string, KeyedRateLimit][] = requests.map((req) => {
            const tokensBefore = budgetById.get(req.id) ?? 0
            // Boundary is `next < 0`, not `<= 0` — needed so the lua's floor-drain of
            // one token under sustained overload actually lets that input through.
            if (tokensBefore >= req.cost) {
                const next = tokensBefore - req.cost
                budgetById.set(req.id, next)
                allowed++
                return [req.id, { tokensBefore, tokens: next, isRateLimited: false }]
            }
            limited++
            return [req.id, { tokensBefore, tokens: -1, isRateLimited: true }]
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
