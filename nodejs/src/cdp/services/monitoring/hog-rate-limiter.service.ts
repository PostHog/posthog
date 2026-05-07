import { RedisV2, getRedisPipelineResults } from '~/common/redis/redis-v2'

export interface HogRateLimiterConfig {
    bucketSize: number
    refillRate: number
    ttl: number
    // When true, dispatches to checkRateLimitV3 (optimized lua: HMGET, multi-field
    // HSET, conditional EXPIRE refresh). Default: V2.
    useV3?: boolean
}

export const BASE_REDIS_KEY =
    process.env.NODE_ENV == 'test' ? '@posthog-test/hog-rate-limiter' : '@posthog/hog-rate-limiter'
const REDIS_KEY_TOKENS = `${BASE_REDIS_KEY}/tokens`

export type HogRateLimit = {
    tokens: number
    isRateLimited: boolean
}

export class HogRateLimiterService {
    constructor(
        private config: HogRateLimiterConfig,
        private redis: RedisV2
    ) {}

    private rateLimitArgs(id: string, cost: number): [string, number, number, number, number, number] {
        const nowSeconds = Math.round(Date.now() / 1000)

        return [
            `${REDIS_KEY_TOKENS}/${id}`,
            nowSeconds,
            cost,
            this.config.bucketSize,
            this.config.refillRate,
            this.config.ttl,
        ]
    }

    public async rateLimitMany(idCosts: [string, number][]): Promise<[string, HogRateLimit][]> {
        const useV3 = this.config.useV3 ?? false
        const res = await this.redis.usePipeline({ name: 'hog-rate-limiter', failOpen: true }, (pipeline) => {
            idCosts.forEach(([id, cost]) => {
                const args = this.rateLimitArgs(id, cost)
                if (useV3) {
                    pipeline.checkRateLimitV3(...args)
                } else {
                    pipeline.checkRateLimitV2(...args)
                }
            })
        })

        if (!res) {
            throw new Error('Failed to rate limit')
        }

        return idCosts.map(([id], index) => {
            const [tokenRes] = getRedisPipelineResults(res, index, 1)
            // checkRateLimit returns [tokensBefore, tokensAfter] for both V2 and V3.
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
