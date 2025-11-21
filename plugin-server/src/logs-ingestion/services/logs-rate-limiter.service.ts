import { RedisV2, getRedisPipelineResults } from '~/common/redis/redis-v2'
import { Hub } from '~/types'

export const BASE_REDIS_KEY =
    process.env.NODE_ENV == 'test' ? '@posthog-test/logs-rate-limiter' : '@posthog/logs-rate-limiter'
const REDIS_KEY_TOKENS = `${BASE_REDIS_KEY}/tokens`

export type LogsRateLimit = {
    tokensBefore: number
    tokensAfter: number
    isRateLimited: boolean
}

/**
 * The LogsRateLimiterService is used to rate limit logs ingestion to ensure we aren't allowing too many logs to be ingested at once.
 * The key part is we specify the refill rate as our per second KB/s limit. and the bucket size as the amount we are allowed to burst to.
 * The burst shouldn't be too much higher.
 */
export class LogsRateLimiterService {
    constructor(
        private hub: Hub,
        private redis: RedisV2
    ) {}

    private rateLimitArgs(id: string, cost: number): [string, number, number, number, number, number] {
        const nowSeconds = Math.round(Date.now() / 1000)

        return [
            `${REDIS_KEY_TOKENS}/${id}`,
            nowSeconds,
            cost,
            this.hub.LOGS_LIMITER_BUCKET_SIZE_KB,
            this.hub.LOGS_LIMITER_REFILL_RATE_KB_PER_SECOND,
            this.hub.LOGS_LIMITER_TTL_SECONDS,
        ]
    }

    public async rateLimitMany(idCosts: [string, number][]): Promise<[string, LogsRateLimit][]> {
        const res = await this.redis.usePipeline({ name: 'logs-rate-limiter', failOpen: true }, (pipeline) => {
            idCosts.forEach(([id, cost]) => {
                pipeline.checkRateLimitV2(...this.rateLimitArgs(id, cost))
            })
        })

        if (!res) {
            throw new Error('Failed to rate limit')
        }

        return idCosts.map(([id], index) => {
            const [tokenRes] = getRedisPipelineResults(res, index, 1)
            const tokensBefore = Number(tokenRes[1]?.[0] ?? this.hub.LOGS_LIMITER_BUCKET_SIZE_KB)
            const tokensAfter = Number(tokenRes[1]?.[1] ?? this.hub.LOGS_LIMITER_BUCKET_SIZE_KB)
            return [
                id,
                {
                    tokensBefore,
                    tokensAfter,
                    isRateLimited: tokensAfter <= 0,
                },
            ]
        })
    }
}
