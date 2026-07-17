import { register } from 'prom-client'

import { deleteKeysWithPrefix } from '~/common/redis/_tests/redis'
import { RedisV2, createRedisV2PoolFromConfig } from '~/common/redis/redis-v2'
import { closeHub, createHub } from '~/common/utils/db/hub'
import { Hub } from '~/types'

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

    describe('metric emission', () => {
        // Counters are module-scoped globals — use deltas (after − before) per
        // test so we don't have to reset shared state between runs.
        const readCounter = async (labels: Record<string, string>): Promise<number> => {
            const metric = register.getSingleMetric('cdp_rate_limiter_claim_total')
            if (!metric) {
                return 0
            }
            const data = await metric.get()
            return data.values
                .filter((v: any) =>
                    Object.entries(labels).every(([k, val]) => (v.labels as Record<string, string>)[k] === val)
                )
                .reduce((sum: number, v: any) => sum + v.value, 0)
        }

        it('increments granted_full when the grant equals the request', async () => {
            const labels = { limiter: 'ses-rate-limiter', key: KEY, result: 'granted_full' }
            const before = await readCounter(labels)

            const granted = await limiter.claimUpTo({ key: KEY, requested: 5, capacity: 10, refillPerSecond: 0 })
            expect(granted).toBe(5)

            const after = await readCounter(labels)
            expect(after - before).toBe(1)
        })

        it('increments granted_partial when the grant is less than the request', async () => {
            // Drain to 2 tokens, then ask for 5.
            await limiter.claimUpTo({ key: KEY, requested: 8, capacity: 10, refillPerSecond: 0 })

            const labels = { limiter: 'ses-rate-limiter', key: KEY, result: 'granted_partial' }
            const before = await readCounter(labels)

            const granted = await limiter.claimUpTo({ key: KEY, requested: 5, capacity: 10, refillPerSecond: 0 })
            expect(granted).toBe(2)

            const after = await readCounter(labels)
            expect(after - before).toBe(1)
        })

        it('increments denied when the bucket is empty', async () => {
            // Drain the bucket fully.
            await limiter.claimUpTo({ key: KEY, requested: 10, capacity: 10, refillPerSecond: 0 })

            const labels = { limiter: 'ses-rate-limiter', key: KEY, result: 'denied' }
            const before = await readCounter(labels)

            const granted = await limiter.claimUpTo({ key: KEY, requested: 5, capacity: 10, refillPerSecond: 0 })
            expect(granted).toBe(0)

            const after = await readCounter(labels)
            expect(after - before).toBe(1)
        })

        it('increments valkey_error when the Lua call throws', async () => {
            // Synthetic broken pool — useClient rejects on every call.
            const brokenValkey = {
                useClient: jest.fn().mockRejectedValue(new Error('connection lost')),
                usePipeline: jest.fn(),
            } as unknown as RedisV2
            const brokenLimiter = new RateLimiterService(brokenValkey, { name: 'broken-limiter' })

            const labels = { limiter: 'broken-limiter', key: KEY, result: 'valkey_error' }
            const before = await readCounter(labels)

            const granted = await brokenLimiter.claimUpTo({
                key: KEY,
                requested: 5,
                capacity: 10,
                refillPerSecond: 0,
            })
            // Fail-closed: thrown error → 0 granted.
            expect(granted).toBe(0)

            const after = await readCounter(labels)
            expect(after - before).toBe(1)
        })
    })
})
