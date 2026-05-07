import { RedisV2, getRedisPipelineResults } from '~/common/redis/redis-v2'

/**
 * Token-bucket rate limiter keyed by an arbitrary string id, backed by Redis.
 *
 * The Redis key prefix is configurable so multiple independent limiters
 * (e.g. error tracking, future per-event-name limits) can share a Redis
 * without colliding. Built on the same `checkRateLimitV2` Lua command that
 * powers `HogRateLimiterService`.
 *
 * Per-call bucket params (bucketSize / refillRate / ttlSeconds on the request)
 * are supported so the same service instance can run different limits for
 * different ids — e.g. per-team overrides without rebuilding the service.
 */
export interface KeyedRateLimiterConfig {
    /**
     * Logical name for this limiter — used to build the Redis key prefix
     * (`@posthog/<name>/tokens/<id>`). In `NODE_ENV=test` the prefix is
     * `@posthog-test/<name>/tokens/<id>` so test runs don't collide with
     * production keys when sharing a Redis.
     */
    name: string
    /**
     * Default bucket params used when a request doesn't specify its own.
     * Optional — callers that always supply per-request overrides can omit them.
     * `rateLimitArgs` throws if a request reaches Redis without either source.
     */
    bucketSize?: number
    refillRate?: number
    ttlSeconds?: number
}

export interface KeyedRateLimitRequest {
    id: string
    cost: number
    /** Override the service's default bucket capacity for this request. */
    bucketSize?: number
    /** Override the service's default replenish rate for this request. */
    refillRate?: number
    /** Override the service's default Redis key TTL for this request. */
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

        if (!res) {
            // failOpen swallowed an error — treat all as not rate limited so we
            // don't drop ingestion just because Redis blipped. Reflect each
            // request's own (potentially overridden) bucketSize in the response.
            return requests.map((req, i) => [req.id, { tokens: bucketSizes[i], isRateLimited: false }])
        }

        return requests.map((req, index) => {
            const [tokenRes] = getRedisPipelineResults(res, index, 1)
            const tokensAfter = tokenRes[1]?.[1] ?? bucketSizes[index]
            return [
                req.id,
                {
                    tokens: Number(tokensAfter),
                    isRateLimited: Number(tokensAfter) <= 0,
                },
            ]
        })
    }

    /**
     * Coalesced variant of `rateLimitMany`: behaves identically from the caller's
     * point of view (parallel `[id, KeyedRateLimit][]` array, same input order),
     * but internally collapses duplicate ids into one Redis call each.
     *
     *   `rateLimitMany`    — N inputs → N pipelined Redis calls (per-call state
     *                        threading via the lua script's stored pool).
     *   `rateLimitGrouped` — N inputs across M unique ids → M pipelined Redis
     *                        calls. Per-input decisions are computed client-side
     *                        from each id's `tokensBefore`: requests are allowed
     *                        in input order until the running cost would exceed
     *                        the pre-batch budget; subsequent over-budget
     *                        requests are denied without consuming budget. For
     *                        uniform cost (the typical CDP case), the per-input
     *                        decisions match `rateLimitMany` exactly.
     *
     * Use `rateLimitGrouped` when the input naturally has many duplicates of
     * the same id (CDP events for a hog function, log lines for a team) — the
     * Redis-call reduction is proportional to the duplication ratio.
     *
     * Always uses the V3 token-bucket script (HMGET + multi-field HSET +
     * conditional EXPIRE refresh). `rateLimitMany` keeps V2 for now; once
     * we're happy with V3 in production, the two methods can converge.
     *
     * Other request params (bucketSize / refillRate / ttlSeconds) are taken
     * from the first request seen for each id; callers should keep those
     * consistent per id (it's the same logical bucket).
     */
    public async rateLimitGrouped(requests: KeyedRateLimitRequest[]): Promise<[string, KeyedRateLimit][]> {
        if (requests.length === 0) {
            return []
        }

        // Coalesce — first request seen per id keeps its bucket params; subsequent
        // requests for the same id contribute their cost to the summed total.
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

        // Pre-batch budget per id (`tokensBefore` from the lua) — used to fan
        // out per-input decisions below. On Redis failure we fail open, so each
        // id's budget defaults to its full bucket size.
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

        // Fan out: walk the original input order, deducting from each id's
        // remaining budget. A request that doesn't fit is denied without
        // consuming budget — subsequent smaller requests for the same id may
        // still fit. For uniform-cost batches this is identical to the
        // pipelined per-call lua behavior.
        return requests.map((req) => {
            const remaining = budgetById.get(req.id) ?? 0
            if (remaining >= req.cost) {
                const next = remaining - req.cost
                budgetById.set(req.id, next)
                return [req.id, { tokens: next, isRateLimited: next <= 0 }]
            }
            return [req.id, { tokens: -1, isRateLimited: true }]
        })
    }
}
