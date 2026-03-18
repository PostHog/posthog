import { RedisV2, getRedisPipelineResults } from '~/common/redis/redis-v2'

export interface HogRateLimiterConfig {
    bucketSize: number
    refillRate: number
    ttl: number
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
        const res = await this.redis.usePipeline({ name: 'hog-rate-limiter', failOpen: true }, (pipeline) => {
            idCosts.forEach(([id, cost]) => {
                pipeline.checkRateLimitV2(...this.rateLimitArgs(id, cost))
            })
        })

        if (!res) {
            throw new Error('Failed to rate limit')
        }

        return idCosts.map(([id], index) => {
            const [tokenRes] = getRedisPipelineResults(res, index, 1)
            // V2 returns [tokensBefore, tokensAfter], we use tokensAfter for backward compatibility
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
