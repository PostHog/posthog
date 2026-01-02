import { RedisV2, getRedisPipelineResults } from '~/common/redis/redis-v2'

import { Hub } from '../../../types'

/** Narrowed Hub type for HogRateLimiterService */
export type HogRateLimiterServiceHub = Pick<
    Hub,
    'CDP_RATE_LIMITER_BUCKET_SIZE' | 'CDP_RATE_LIMITER_REFILL_RATE' | 'CDP_RATE_LIMITER_TTL'
>

export const BASE_REDIS_KEY =
    process.env.NODE_ENV == 'test' ? '@posthog-test/hog-rate-limiter' : '@posthog/hog-rate-limiter'
const REDIS_KEY_TOKENS = `${BASE_REDIS_KEY}/tokens`

export type HogRateLimit = {
    tokens: number
    isRateLimited: boolean
}

export class HogRateLimiterService {
    constructor(
        private hub: HogRateLimiterServiceHub,
        private redis: RedisV2
    ) {}

    private rateLimitArgs(id: string, cost: number): [string, number, number, number, number, number] {
        const nowSeconds = Math.round(Date.now() / 1000)

        return [
            `${REDIS_KEY_TOKENS}/${id}`,
            nowSeconds,
            cost,
            this.hub.CDP_RATE_LIMITER_BUCKET_SIZE,
            this.hub.CDP_RATE_LIMITER_REFILL_RATE,
            this.hub.CDP_RATE_LIMITER_TTL,
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
            const tokensAfter = tokenRes[1]?.[1] ?? this.hub.CDP_RATE_LIMITER_BUCKET_SIZE
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
