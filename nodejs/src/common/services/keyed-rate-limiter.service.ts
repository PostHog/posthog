import { RedisV2, getRedisPipelineResults } from '~/common/redis/redis-v2'

/**
 * Token-bucket rate limiter keyed by an arbitrary string id, backed by Redis.
 *
 * The Redis key prefix is configurable so multiple independent limiters
 * (e.g. error tracking, future per-event-name limits) can share a Redis
 * without colliding. Built on the same `checkRateLimitV2` Lua command that
 * powers `HogRateLimiterService`.
 */
export interface KeyedRateLimiterConfig {
    /**
     * Logical name for this limiter — used to build the Redis key prefix
     * (`@posthog/<name>/tokens/<id>`). In `NODE_ENV=test` the prefix is
     * `@posthog-test/<name>/tokens/<id>` so test runs don't collide with
     * production keys when sharing a Redis.
     */
    name: string
    bucketSize: number
    refillRate: number
    ttlSeconds: number
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

    private rateLimitArgs(id: string, cost: number): [string, number, number, number, number, number] {
        const nowSeconds = Math.round(Date.now() / 1000)
        return [
            `${this.keyPrefix}/${id}`,
            nowSeconds,
            cost,
            this.config.bucketSize,
            this.config.refillRate,
            this.config.ttlSeconds,
        ]
    }

    public async rateLimitMany(idCosts: [string, number][]): Promise<[string, KeyedRateLimit][]> {
        if (idCosts.length === 0) {
            return []
        }

        const res = await this.redis.usePipeline(
            { name: `keyed-rate-limiter:${this.config.name}`, failOpen: true },
            (pipeline) => {
                idCosts.forEach(([id, cost]) => {
                    pipeline.checkRateLimitV2(...this.rateLimitArgs(id, cost))
                })
            }
        )

        if (!res) {
            // failOpen swallowed an error — treat all as not rate limited so we
            // don't drop ingestion just because Redis blipped.
            return idCosts.map(([id]) => [id, { tokens: this.config.bucketSize, isRateLimited: false }])
        }

        return idCosts.map(([id], index) => {
            const [tokenRes] = getRedisPipelineResults(res, index, 1)
            const tokensAfter = tokenRes[1]?.[1] ?? this.config.bucketSize
            return [
                id,
                {
                    tokens: Number(tokensAfter),
                    isRateLimited: Number(tokensAfter) <= 0,
                },
            ]
        })
    }
}
