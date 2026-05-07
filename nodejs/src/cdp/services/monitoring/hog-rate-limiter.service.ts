import { RedisV2, getRedisPipelineResults } from '~/common/redis/redis-v2'

import { checkRateLimitV3Many } from '../../../common/redis/redis-token-bucket-v3.lua'

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
            // checkRateLimitV2 returns [tokensBefore, tokensAfter].
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

    /**
     * Single-script multi-key variant: collapses N pipelined evalsha calls into
     * one, amortizing the Lua-interpreter overhead across all buckets. Requires
     * the V3 multi-key script (`checkRateLimitV3Many`) to be available on the
     * client. Currently used only on the Valkey mirror path — see
     * cdp-events.consumer.ts.
     */
    public async rateLimitManyMulti(idCosts: [string, number][]): Promise<[string, HogRateLimit][]> {
        if (idCosts.length === 0) {
            return []
        }
        const buckets = idCosts.map(([id, cost]) => {
            const [key, now, costN, poolMax, fillRate, expiry] = this.rateLimitArgs(id, cost)
            return { key, now, cost: costN, poolMax, fillRate, expiry }
        })
        const tuples = await this.redis.useClient(
            { name: 'hog-rate-limiter-multi', failOpen: true },
            async (client) => {
                return await checkRateLimitV3Many(client, buckets)
            }
        )
        if (!tuples) {
            throw new Error('Failed to rate limit (multi)')
        }
        return idCosts.map(([id], index) => {
            const tokensAfter = tuples[index]?.[1] ?? this.config.bucketSize
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
