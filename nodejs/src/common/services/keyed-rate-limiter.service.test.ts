import { RedisV2, createRedisV2PoolFromConfig } from '~/common/redis/redis-v2'
import { Hub } from '~/types'
import { closeHub, createHub } from '~/utils/db/hub'

import { deleteKeysWithPrefix } from '../../cdp/_tests/redis'
import { KeyedRateLimiterService } from './keyed-rate-limiter.service'

const mockNow: jest.SpyInstance = jest.spyOn(Date, 'now')

describe('KeyedRateLimiterService', () => {
    jest.retryTimes(3)

    let now: number
    let hub: Hub
    let redis: RedisV2

    const advanceTime = (ms: number) => {
        now += ms
        mockNow.mockReturnValue(now)
    }

    beforeEach(async () => {
        hub = await createHub()
        now = 1720000000000
        mockNow.mockReturnValue(now)

        redis = createRedisV2PoolFromConfig({
            connection: hub.CDP_REDIS_HOST
                ? {
                      url: hub.CDP_REDIS_HOST,
                      options: { port: hub.CDP_REDIS_PORT, password: hub.CDP_REDIS_PASSWORD },
                  }
                : { url: hub.REDIS_URL },
            poolMinSize: hub.REDIS_POOL_MIN_SIZE,
            poolMaxSize: hub.REDIS_POOL_MAX_SIZE,
        })
    })

    afterEach(async () => {
        await closeHub(hub)
        jest.clearAllMocks()
    })

    const buildLimiter = (name: string, overrides: Partial<{ bucketSize: number; refillRate: number }> = {}) =>
        new KeyedRateLimiterService(
            {
                name,
                bucketSize: overrides.bucketSize ?? 100,
                refillRate: overrides.refillRate ?? 10,
                ttlSeconds: 60 * 60 * 24,
            },
            redis
        )

    it('uses tokens for an id', async () => {
        const limiter = buildLimiter('test-basic')
        await deleteKeysWithPrefix(redis, limiter.getKeyPrefix())

        const res = await limiter.rateLimitMany([{ id: 'team-1', cost: 1 }])

        expect(res).toEqual([['team-1', { tokens: 99, isRateLimited: false }]])
    })

    it('rate limits when exceeding the bucket', async () => {
        const limiter = buildLimiter('test-exceed')
        await deleteKeysWithPrefix(redis, limiter.getKeyPrefix())

        let res = await limiter.rateLimitMany([{ id: 'team-1', cost: 99 }])
        expect(res[0][1]).toEqual({ tokens: 1, isRateLimited: false })

        res = await limiter.rateLimitMany([{ id: 'team-1', cost: 1 }])
        expect(res[0][1]).toEqual({ tokens: 0, isRateLimited: true })

        res = await limiter.rateLimitMany([{ id: 'team-1', cost: 20 }])
        expect(res[0][1].isRateLimited).toBe(true)
    })

    it('refills over time according to refillRate', async () => {
        const limiter = buildLimiter('test-refill')
        await deleteKeysWithPrefix(redis, limiter.getKeyPrefix())

        let res = await limiter.rateLimitMany([{ id: 'team-1', cost: 50 }])
        expect(res[0][1].tokens).toBe(50)

        advanceTime(1000)
        res = await limiter.rateLimitMany([{ id: 'team-1', cost: 0 }])
        expect(res[0][1].tokens).toBe(60)
    })

    it('isolates ids that share a limiter via different keys', async () => {
        const limiter = buildLimiter('test-multi')
        await deleteKeysWithPrefix(redis, limiter.getKeyPrefix())

        const res = await limiter.rateLimitMany([
            { id: 'team-1', cost: 1 },
            { id: 'team-2', cost: 5 },
        ])

        expect(res).toEqual([
            ['team-1', { tokens: 99, isRateLimited: false }],
            ['team-2', { tokens: 95, isRateLimited: false }],
        ])
    })

    it('isolates two limiters that share a Redis via different prefixes', async () => {
        const limiterA = buildLimiter('test-prefix-a')
        const limiterB = buildLimiter('test-prefix-b')
        await deleteKeysWithPrefix(redis, limiterA.getKeyPrefix())
        await deleteKeysWithPrefix(redis, limiterB.getKeyPrefix())

        // Drain limiter A entirely.
        await limiterA.rateLimitMany([{ id: 'shared-id', cost: 100 }])
        const drainedA = await limiterA.rateLimitMany([{ id: 'shared-id', cost: 1 }])
        expect(drainedA[0][1].isRateLimited).toBe(true)

        // Same id under limiter B is untouched — confirms prefix isolation.
        const freshB = await limiterB.rateLimitMany([{ id: 'shared-id', cost: 1 }])
        expect(freshB[0][1]).toEqual({ tokens: 99, isRateLimited: false })
    })

    it('uses test-prefixed redis keys when NODE_ENV=test', () => {
        const limiter = buildLimiter('node-env-check')
        expect(limiter.getKeyPrefix().startsWith('@posthog-test/')).toBe(true)
    })

    it('returns empty array for empty input without touching Redis', async () => {
        const limiter = buildLimiter('test-empty')
        const res = await limiter.rateLimitMany([])
        expect(res).toEqual([])
    })

    it('fails open when the Redis pipeline fails', async () => {
        const limiter = new KeyedRateLimiterService(
            { name: 'test-fail-open', bucketSize: 50, refillRate: 1, ttlSeconds: 60 },
            {
                useClient: jest.fn(),
                // Simulate the failOpen path inside RedisV2: usePipeline returns null on error.
                usePipeline: jest.fn().mockResolvedValue(null),
            } as unknown as RedisV2
        )

        const res = await limiter.rateLimitMany([
            { id: 'a', cost: 1 },
            { id: 'b', cost: 2 },
        ])

        expect(res).toEqual([
            ['a', { tokens: 50, isRateLimited: false }],
            ['b', { tokens: 50, isRateLimited: false }],
        ])
    })

    it('honours per-call bucketSize and refillRate overrides', async () => {
        const limiter = buildLimiter('test-per-call', { bucketSize: 100, refillRate: 10 })
        await deleteKeysWithPrefix(redis, limiter.getKeyPrefix())

        // Per-call override: tiny bucket of 5, despite the service's default of 100.
        const res = await limiter.rateLimitMany([{ id: 'tiny-team', cost: 6, bucketSize: 5, refillRate: 1 }])

        expect(res[0][1].isRateLimited).toBe(true)
    })
})
