import { Hub } from '../../../types'
import { CdpRedis, getRedisPipelineResults } from '../../redis'

export const BASE_REDIS_KEY =
    process.env.NODE_ENV == 'test' ? '@posthog-test/hog-rate-limiter' : '@posthog/hog-rate-limiter'
const REDIS_KEY_TOKENS = `${BASE_REDIS_KEY}/tokens`

export type HogRateLimit = {
    tokens: number
    isRateLimited: boolean
}

export class HogRateLimiterService {
    constructor(
        private hub: Hub,
        private redis: CdpRedis
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
        ] as const
    }

    public async rateLimitMany(idCosts: Record<string, number>): Promise<Record<string, HogRateLimit>> {
        const res = await this.redis.usePipeline({ name: 'hog-rate-limiter', failOpen: true }, (pipeline) => {
            Object.entries(idCosts).forEach(([id, cost]) => {
                pipeline.checkRateLimit(...this.rateLimitArgs(id, cost))
            })
        })

        if (!res) {
            return {}
        }

        return Object.keys(idCosts).reduce(
            (acc, id, index) => {
                const [tokenRes] = getRedisPipelineResults(res, index, 1)
                const token = tokenRes[1]
                acc[id] = {
                    tokens: Number(token ?? this.hub.CDP_RATE_LIMITER_BUCKET_SIZE),
                    isRateLimited: Number(token ?? this.hub.CDP_RATE_LIMITER_BUCKET_SIZE) <= 0,
                }
                return acc
            },
            {} as Record<string, HogRateLimit>
        )
    }
}
