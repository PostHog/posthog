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
    /** Default bucket params used when a request doesn't specify its own. */
    bucketSize: number
    refillRate: number
    ttlSeconds: number
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
        return [
            `${this.keyPrefix}/${req.id}`,
            nowSeconds,
            req.cost,
            req.bucketSize ?? this.config.bucketSize,
            req.refillRate ?? this.config.refillRate,
            req.ttlSeconds ?? this.config.ttlSeconds,
        ]
    }

    public async rateLimitMany(requests: KeyedRateLimitRequest[]): Promise<[string, KeyedRateLimit][]> {
        if (requests.length === 0) {
            return []
        }

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
            return requests.map((req) => [
                req.id,
                { tokens: req.bucketSize ?? this.config.bucketSize, isRateLimited: false },
            ])
        }

        return requests.map((req, index) => {
            const [tokenRes] = getRedisPipelineResults(res, index, 1)
            const tokensAfter = tokenRes[1]?.[1] ?? req.bucketSize ?? this.config.bucketSize
            return [
                req.id,
                {
                    tokens: Number(tokensAfter),
                    isRateLimited: Number(tokensAfter) <= 0,
                },
            ]
        })
    }
}
