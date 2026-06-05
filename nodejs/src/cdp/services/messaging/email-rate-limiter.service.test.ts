import { RedisV2, createRedisV2PoolFromConfig } from '~/common/redis/redis-v2'
import { getDefaultConfig } from '~/config/config'

import { EMAIL_RATE_LIMITER_KEY, EMAIL_RATE_LIMITER_NAME, EmailRateLimiterService } from './email-rate-limiter.service'

// The KeyedRateLimiterService key prefix in NODE_ENV=test:
const KEY_PREFIX = `@posthog-test/${EMAIL_RATE_LIMITER_NAME}/tokens/${EMAIL_RATE_LIMITER_KEY}`

describe('EmailRateLimiterService', () => {
    let redis: RedisV2

    beforeAll(() => {
        const config = getDefaultConfig()
        redis = createRedisV2PoolFromConfig({
            connection: {
                url: config.CDP_REDIS_HOST,
                options: { port: config.CDP_REDIS_PORT },
                name: 'email-rate-limiter-test',
            },
            poolMinSize: 1,
            poolMaxSize: 3,
        })
    })

    beforeEach(async () => {
        await redis.useClient({ name: 'test-cleanup' }, async (client) => {
            await client.del(KEY_PREFIX)
        })
    })

    it('allows the whole batch when bucket has capacity', async () => {
        const limiter = new EmailRateLimiterService({ bucketSize: 100, refillRate: 10 }, redis)

        const decision = await limiter.decide(10)

        expect(decision).toMatchObject({ processCount: 10, deferCount: 0 })
    })

    it('partial-consumes when the batch exceeds available tokens', async () => {
        const limiter = new EmailRateLimiterService({ bucketSize: 5, refillRate: 0.0001 }, redis)

        // First batch drains the bucket (5 tokens consumed, 0 left).
        await limiter.decide(5)

        // Second batch of 3 — refill is negligible, so 0 should process and all 3 defer.
        const decision = await limiter.decide(3)

        expect(decision.processCount).toBe(0)
        expect(decision.deferCount).toBe(3)
    })

    it('processes the available portion when batch is larger than budget', async () => {
        const limiter = new EmailRateLimiterService({ bucketSize: 5, refillRate: 0.0001 }, redis)

        const decision = await limiter.decide(10)

        // First call denied (cost=10 > 5), second call consumes floor(5)=5.
        expect(decision.processCount).toBe(5)
        expect(decision.deferCount).toBe(5)
    })

    it('returns a no-op decision for an empty batch', async () => {
        const limiter = new EmailRateLimiterService({ bucketSize: 100, refillRate: 10 }, redis)

        const decision = await limiter.decide(0)

        expect(decision).toEqual({ processCount: 0, deferCount: 0, tokensAfter: 100 })
    })

    it('propagates the error when the pipeline fails (callers fail-open at the consumer)', async () => {
        const brokenRedis = {
            usePipeline: jest.fn().mockResolvedValue(null),
        } as unknown as RedisV2

        const limiter = new EmailRateLimiterService({ bucketSize: 5, refillRate: 1 }, brokenRedis)

        await expect(limiter.decide(3)).rejects.toThrow()
    })
})
