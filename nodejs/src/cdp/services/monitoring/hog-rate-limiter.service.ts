import { RedisV2, getRedisPipelineResults } from '~/common/redis/redis-v2'

export interface HogRateLimiterConfig {
    bucketSize: number
    refillRate: number
    ttl: number
    deferredGraceMs: number
}

export const BASE_REDIS_KEY =
    process.env.NODE_ENV == 'test' ? '@posthog-test/hog-rate-limiter' : '@posthog/hog-rate-limiter'
const REDIS_KEY_TOKENS = `${BASE_REDIS_KEY}/tokens`
const REDIS_KEY_DEFERRED = `${BASE_REDIS_KEY}/deferred`

export type HogRateLimit = {
    tokens: number
    isRateLimited: boolean
}

export type HogDeferResult = {
    accepted: boolean
    scheduledAtMs: number
}

export class HogRateLimiterService {
    constructor(
        private config: HogRateLimiterConfig,
        private redis: RedisV2
    ) {
        if (config.refillRate <= 0) {
            throw new Error(
                `HogRateLimiterService requires a positive refillRate (got ${config.refillRate}); this would produce invalid scheduled times for deferred invocations.`
            )
        }
        if (config.bucketSize <= 0) {
            throw new Error(`HogRateLimiterService requires a positive bucketSize (got ${config.bucketSize}).`)
        }
    }

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

    // Throws on Redis failure so the caller can let the batch retry rather than silently
    // bypassing rate limiting.
    public async tryDeferMany(
        items: { flowId: string; invocationId: string }[],
        maxDeferred: number
    ): Promise<HogDeferResult[]> {
        if (items.length === 0) {
            return []
        }

        const nowMs = Date.now()
        const res = await this.redis.usePipeline({ name: 'hog-rate-limiter-defer', failOpen: true }, (pipeline) => {
            items.forEach(({ flowId, invocationId }) => {
                pipeline.deferInvocation(
                    `${REDIS_KEY_DEFERRED}/${flowId}`,
                    nowMs,
                    this.config.refillRate,
                    maxDeferred,
                    this.config.ttl,
                    invocationId,
                    this.config.deferredGraceMs
                )
            })
        })

        if (!res) {
            throw new Error('Failed to defer invocations')
        }

        return items.map((_, index) => {
            const [deferRes] = getRedisPipelineResults(res, index, 1)
            const accepted = Number(deferRes[1]?.[0] ?? 0)
            const scheduledAtMs = Number(deferRes[1]?.[1] ?? 0)
            return {
                accepted: accepted === 1,
                scheduledAtMs,
            }
        })
    }

    public async tryDefer(flowId: string, invocationId: string, maxDeferred: number): Promise<HogDeferResult> {
        const [result] = await this.tryDeferMany([{ flowId, invocationId }], maxDeferred)
        return result
    }
}
