import { RedisV2, createRedisV2PoolFromConfig } from '~/common/redis/redis-v2'
import { Hub } from '~/types'
import { closeHub, createHub } from '~/utils/db/hub'

import { deleteKeysWithPrefix } from '../../_tests/redis'
import { RateLimiterService } from './rate-limiter.service'

const KEY = '@posthog-test/ses-rate-limiter/bucket'

describe('RateLimiterService', () => {
    jest.retryTimes(3)

    let hub: Hub
    let redis: RedisV2
    let limiter: RateLimiterService

    beforeEach(async () => {
        hub = await createHub()
        // Reuse the local CDP Redis for tests — same wire protocol, same atomicity.
        // In production this points at the dedicated SES rate-limiter Valkey.
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
        limiter = new RateLimiterService(redis, { name: 'ses-rate-limiter' })
        await deleteKeysWithPrefix(redis, '@posthog-test/ses-rate-limiter')
    })

    afterEach(async () => {
        await closeHub(hub)
    })

    it('cold-starts at full capacity', async () => {
        const granted = await limiter.claimUpTo({
            key: KEY,
            requested: 50,
            capacity: 50,
            refillPerSecond: 100,
        })
        expect(granted).toBe(50)
    })

    it('returns 0 when the bucket is drained', async () => {
        await limiter.claimUpTo({ key: KEY, requested: 50, capacity: 50, refillPerSecond: 100 })
        // Second claim immediately after — refill in 0ms is negligible, ~0 tokens available
        const granted = await limiter.claimUpTo({
            key: KEY,
            requested: 50,
            capacity: 50,
            refillPerSecond: 100,
        })
        expect(granted).toBeLessThan(5)
    })

    it('grants partial when fewer tokens are available than requested', async () => {
        // First, drain 40 of 50.
        await limiter.claimUpTo({ key: KEY, requested: 40, capacity: 50, refillPerSecond: 0 })
        // refillPerSecond=0 keeps the residual at exactly 10 tokens.
        const granted = await limiter.claimUpTo({
            key: KEY,
            requested: 50,
            capacity: 50,
            refillPerSecond: 0,
        })
        expect(granted).toBe(10)
    })

    it('refills tokens over time', async () => {
        await limiter.claimUpTo({ key: KEY, requested: 50, capacity: 50, refillPerSecond: 100 })
        // Wait 200ms — at 100 tokens/sec, ~20 tokens should refill.
        await new Promise((resolve) => setTimeout(resolve, 200))
        const granted = await limiter.claimUpTo({
            key: KEY,
            requested: 50,
            capacity: 50,
            refillPerSecond: 100,
        })
        // Allow a wide margin — real-time-based, can vary on busy CI.
        expect(granted).toBeGreaterThanOrEqual(10)
        expect(granted).toBeLessThanOrEqual(30)
    })

    it('atomically serializes concurrent claims so the sum never exceeds capacity', async () => {
        // Two pods racing for the same bucket. Single Lua script per call → Valkey
        // serializes them, so the sum-of-grants is bounded by the bucket capacity.
        const N = 5
        const claims = await Promise.all(
            Array.from({ length: N }, () =>
                limiter.claimUpTo({ key: KEY, requested: 50, capacity: 50, refillPerSecond: 0 })
            )
        )
        const total = claims.reduce((a, b) => a + b, 0)
        expect(total).toBe(50)
        // Exactly one caller got the full bucket; the rest got 0.
        expect(claims.filter((c) => c > 0)).toHaveLength(1)
    })

    it('caps tokens at capacity even after long idle', async () => {
        await limiter.claimUpTo({ key: KEY, requested: 50, capacity: 50, refillPerSecond: 1000 })
        // Wait long enough that uncapped accrual would exceed capacity.
        await new Promise((resolve) => setTimeout(resolve, 100))
        const granted = await limiter.claimUpTo({
            key: KEY,
            requested: 1000,
            capacity: 50,
            refillPerSecond: 1000,
        })
        expect(granted).toBe(50)
    })
})
