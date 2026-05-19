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

    const buildLimiter = (
        name: string,
        overrides: Partial<{ bucketSize: number; refillRate: number; ttlSeconds: number }> = {}
    ) =>
        new KeyedRateLimiterService(
            {
                name,
                bucketSize: overrides.bucketSize ?? 100,
                refillRate: overrides.refillRate ?? 10,
                ttlSeconds: overrides.ttlSeconds ?? 60 * 60 * 24,
            },
            redis
        )

    const readBucket = async (key: string): Promise<{ ts: string | null; pool: string | null }> => {
        const result = await redis.useClient({ name: 'read-bucket' }, async (client) => {
            const [ts, pool] = await Promise.all([client.hget(key, 'ts'), client.hget(key, 'pool')])
            return { ts, pool }
        })
        return result ?? { ts: null, pool: null }
    }

    describe('rateLimitGrouped', () => {
        it('uses tokens for an id', async () => {
            const limiter = buildLimiter('test-basic')
            await deleteKeysWithPrefix(redis, limiter.getKeyPrefix())

            const res = await limiter.rateLimitGrouped([{ id: 'team-1', cost: 1 }])

            expect(res).toEqual([['team-1', { tokens: 99, isRateLimited: false }]])
        })

        it('rate limits when exceeding the bucket', async () => {
            const limiter = buildLimiter('test-exceed')
            await deleteKeysWithPrefix(redis, limiter.getKeyPrefix())

            let res = await limiter.rateLimitGrouped([{ id: 'team-1', cost: 99 }])
            expect(res[0][1]).toEqual({ tokens: 1, isRateLimited: false })

            res = await limiter.rateLimitGrouped([{ id: 'team-1', cost: 1 }])
            expect(res[0][1]).toEqual({ tokens: 0, isRateLimited: true })

            res = await limiter.rateLimitGrouped([{ id: 'team-1', cost: 20 }])
            expect(res[0][1].isRateLimited).toBe(true)
        })

        it('refills over time according to refillRate', async () => {
            const limiter = buildLimiter('test-refill')
            await deleteKeysWithPrefix(redis, limiter.getKeyPrefix())

            let res = await limiter.rateLimitGrouped([{ id: 'team-1', cost: 50 }])
            expect(res[0][1].tokens).toBe(50)

            advanceTime(1000)
            res = await limiter.rateLimitGrouped([{ id: 'team-1', cost: 0 }])
            expect(res[0][1].tokens).toBe(60)
        })

        it('isolates ids that share a limiter via different keys', async () => {
            const limiter = buildLimiter('test-multi')
            await deleteKeysWithPrefix(redis, limiter.getKeyPrefix())

            const res = await limiter.rateLimitGrouped([
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

            await limiterA.rateLimitGrouped([{ id: 'shared-id', cost: 100 }])
            const drainedA = await limiterA.rateLimitGrouped([{ id: 'shared-id', cost: 1 }])
            expect(drainedA[0][1].isRateLimited).toBe(true)

            // Same id under limiter B is untouched — confirms prefix isolation.
            const freshB = await limiterB.rateLimitGrouped([{ id: 'shared-id', cost: 1 }])
            expect(freshB[0][1]).toEqual({ tokens: 99, isRateLimited: false })
        })

        it('uses test-prefixed redis keys when NODE_ENV=test', () => {
            const limiter = buildLimiter('node-env-check')
            expect(limiter.getKeyPrefix().startsWith('@posthog-test/')).toBe(true)
        })

        it('honours per-call bucketSize and refillRate overrides', async () => {
            const limiter = buildLimiter('test-per-call')
            await deleteKeysWithPrefix(redis, limiter.getKeyPrefix())

            // Per-call override: tiny bucket of 5, despite the service's default of 100.
            const res = await limiter.rateLimitGrouped([{ id: 'tiny-team', cost: 6, bucketSize: 5, refillRate: 1 }])

            expect(res[0][1].isRateLimited).toBe(true)
        })

        it('returns -1 when first cost exceeds pool size', async () => {
            const limiter = buildLimiter('test-first-exceed')
            await deleteKeysWithPrefix(redis, limiter.getKeyPrefix())

            const res = await limiter.rateLimitGrouped([{ id: 'team-1', cost: 150 }])
            expect(res[0][1].tokens).toBe(-1)
            expect(res[0][1].isRateLimited).toBe(true)
        })

        it('treats cost=0 as a peek without changing tokens', async () => {
            const limiter = buildLimiter('test-cost-zero')
            await deleteKeysWithPrefix(redis, limiter.getKeyPrefix())

            await limiter.rateLimitGrouped([{ id: 'team-1', cost: 30 }])
            const res = await limiter.rateLimitGrouped([{ id: 'team-1', cost: 0 }])
            expect(res[0][1].tokens).toBe(70)
        })

        it('still rate-limits when a catch-up cost exceeds accrued credit', async () => {
            const limiter = buildLimiter('test-catchup-exceeds')
            await deleteKeysWithPrefix(redis, limiter.getKeyPrefix())

            await limiter.rateLimitGrouped([{ id: 'team-1', cost: 100 }]) // pool=0
            advanceTime(5_000) // 5s × 10/s = 50 accrued
            const res = await limiter.rateLimitGrouped([{ id: 'team-1', cost: 60 }])
            expect(res[0][1].isRateLimited).toBe(true)
        })

        it('returns one decision per input request (parallel to input order)', async () => {
            const limiter = buildLimiter('grouped-shape')
            await deleteKeysWithPrefix(redis, limiter.getKeyPrefix())

            const res = await limiter.rateLimitGrouped([
                { id: 'team-1', cost: 1 },
                { id: 'team-2', cost: 1 },
                { id: 'team-1', cost: 1 },
            ])

            expect(res).toHaveLength(3)
            expect(res[0][0]).toBe('team-1')
            expect(res[1][0]).toBe('team-2')
            expect(res[2][0]).toBe('team-1')
        })

        it('allows the first N inputs of an over-budget batch and denies the rest', async () => {
            // 10 cost-1 requests against a bucket of 4. `isRateLimited = tokens <= 0`,
            // so the 4th request (which brings tokens to exactly 0) is flagged as
            // rate-limited even though its cost was paid. The remaining 6 hit tokens=-1.
            const limiter = buildLimiter('grouped-fanout', { bucketSize: 4, refillRate: 0 })
            await deleteKeysWithPrefix(redis, limiter.getKeyPrefix())

            const requests = Array.from({ length: 10 }, () => ({ id: 'team-1', cost: 1 }))
            const res = await limiter.rateLimitGrouped(requests)

            expect(res.map(([, r]) => r.tokens)).toEqual([3, 2, 1, 0, -1, -1, -1, -1, -1, -1])
            expect(res.map(([, r]) => r.isRateLimited)).toEqual([
                false,
                false,
                false,
                true, // tokens=0 — boundary, flagged as rate-limited
                true,
                true,
                true,
                true,
                true,
                true,
            ])
        })

        it('keeps independent budgets per id', async () => {
            const limiter = buildLimiter('grouped-multi-id', { bucketSize: 2, refillRate: 0 })
            await deleteKeysWithPrefix(redis, limiter.getKeyPrefix())

            // Two ids interleaved with 3 cost-1 requests each. Each id's budget
            // of 2 fits its 1st request cleanly (tokens=1), depletes on the 2nd
            // (tokens=0 → rate-limited boundary), and denies the 3rd (tokens=-1).
            // If the budgets were shared, t2's first call would already be
            // rate-limited because t1 would have drained the shared bucket.
            const res = await limiter.rateLimitGrouped([
                { id: 'team-1', cost: 1 },
                { id: 'team-2', cost: 1 },
                { id: 'team-1', cost: 1 },
                { id: 'team-2', cost: 1 },
                { id: 'team-1', cost: 1 },
                { id: 'team-2', cost: 1 },
            ])

            expect(res.map(([, r]) => r.tokens)).toEqual([1, 1, 0, 0, -1, -1])
            expect(res.map(([, r]) => r.isRateLimited)).toEqual([false, false, true, true, true, true])
        })

        it('issues exactly one Redis dispatch per unique id (call-count win)', async () => {
            // 10 cost-1 requests for the same id → 1 evalsha.
            const limiter = buildLimiter('grouped-dispatch-count')
            await deleteKeysWithPrefix(redis, limiter.getKeyPrefix())

            const before = await redis.useClient({ name: 'before' }, async (client) => client.info('commandstats'))
            await redis.useClient({ name: 'reset' }, async (client) => client.config('RESETSTAT'))

            const requests = Array.from({ length: 10 }, () => ({ id: 'team-1', cost: 1 }))
            await limiter.rateLimitGrouped(requests)

            const after = await redis.useClient({ name: 'after' }, async (client) => client.info('commandstats'))
            const evalshaMatch = /cmdstat_evalsha:calls=(\d+)/.exec(after ?? '')
            const evalshaCount = evalshaMatch ? Number(evalshaMatch[1]) : 0
            expect(evalshaCount).toBe(1)

            // Sanity: at least proves we read INFO before/after, not testing those.
            expect(typeof before).toBe('string')
        })

        it('returns empty array for empty input without touching Redis', async () => {
            const limiter = buildLimiter('grouped-empty')
            const res = await limiter.rateLimitGrouped([])
            expect(res).toEqual([])
        })

        it('fails open when the Redis pipeline fails', async () => {
            const limiter = new KeyedRateLimiterService(
                { name: 'grouped-fail-open', bucketSize: 50, refillRate: 1, ttlSeconds: 60 },
                {
                    useClient: jest.fn(),
                    usePipeline: jest.fn().mockResolvedValue(null),
                } as unknown as RedisV2
            )

            const res = await limiter.rateLimitGrouped([
                { id: 'a', cost: 1 },
                { id: 'b', cost: 2 },
                { id: 'a', cost: 1 },
            ])

            expect(res.map(([id]) => id)).toEqual(['a', 'b', 'a'])
            // All three allowed — fail-open assumes full bucket.
            expect(res.every(([, r]) => !r.isRateLimited)).toBe(true)
        })

        // V3-specific behavior — migrated from redis-token-bucket-v3.lua.test.ts.

        it('exposes uncapped accrued credit (PR 57920 contract)', async () => {
            const limiter = buildLimiter('grouped-accrued')
            await deleteKeysWithPrefix(redis, limiter.getKeyPrefix())

            await limiter.rateLimitGrouped([{ id: 'team-1', cost: 100 }]) // pool=0
            advanceTime(20_000) // 20s × 10/s = 200 accrued
            const res = await limiter.rateLimitGrouped([{ id: 'team-1', cost: 199 }])
            // Catch-up call redeems 199 of the 200 accrued credit.
            expect(res).toEqual([['team-1', { tokens: 1, isRateLimited: false }]])
        })

        it('sets TTL to 2x ttlSeconds on creation (V3 ceiling)', async () => {
            const limiter = buildLimiter('grouped-ttl-create', { ttlSeconds: 60 })
            await deleteKeysWithPrefix(redis, limiter.getKeyPrefix())
            const key = `${limiter.getKeyPrefix()}/team-1`

            await limiter.rateLimitGrouped([{ id: 'team-1', cost: 5 }])

            const ttl = await redis.useClient({ name: 'ttl-check' }, async (client) => await client.ttl(key))
            expect(ttl).toBeGreaterThan(60)
            expect(ttl).toBeLessThanOrEqual(120)
        })

        it('does NOT refresh TTL while remaining is above ttlSeconds/2', async () => {
            const limiter = buildLimiter('grouped-ttl-stable', { ttlSeconds: 60 })
            await deleteKeysWithPrefix(redis, limiter.getKeyPrefix())
            const key = `${limiter.getKeyPrefix()}/team-1`

            await limiter.rateLimitGrouped([{ id: 'team-1', cost: 1 }])
            // Force PTTL to ~50s — well above the 30s threshold (ttlSeconds/2).
            await redis.useClient({ name: 'pexpire' }, async (client) => await client.pexpire(key, 50_000))
            await limiter.rateLimitGrouped([{ id: 'team-1', cost: 1 }])

            const ttlMs = await redis.useClient({ name: 'pttl-check' }, async (client) => await client.pttl(key))
            expect(ttlMs).toBeGreaterThan(0)
            expect(ttlMs).toBeLessThanOrEqual(50_000)
        })

        it('refreshes TTL once remaining drops below ttlSeconds/2', async () => {
            const limiter = buildLimiter('grouped-ttl-refresh', { ttlSeconds: 60 })
            await deleteKeysWithPrefix(redis, limiter.getKeyPrefix())
            const key = `${limiter.getKeyPrefix()}/team-1`

            await limiter.rateLimitGrouped([{ id: 'team-1', cost: 1 }])
            // Force PTTL to ~10s — well below the 30s threshold.
            await redis.useClient({ name: 'pexpire' }, async (client) => await client.pexpire(key, 10_000))
            await limiter.rateLimitGrouped([{ id: 'team-1', cost: 1 }])

            const ttlMs = await redis.useClient({ name: 'pttl-check' }, async (client) => await client.pttl(key))
            // Refresh fired — TTL bounces back near 2 × ttlSeconds (= 120s).
            expect(ttlMs).toBeGreaterThan(60_000)
            expect(ttlMs).toBeLessThanOrEqual(120_000)
        })

        it('persists ts + pool to redis (storage shape unchanged from V2)', async () => {
            const limiter = buildLimiter('grouped-persist')
            await deleteKeysWithPrefix(redis, limiter.getKeyPrefix())
            const key = `${limiter.getKeyPrefix()}/team-1`

            await limiter.rateLimitGrouped([{ id: 'team-1', cost: 5 }])
            const stored = await readBucket(key)
            expect(stored.ts).toBe(String(Math.round(now / 1000)))
            expect(stored.pool).toBe('95')
        })
    })
})
