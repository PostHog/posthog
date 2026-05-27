import { RedisV2, createRedisV2PoolFromConfig } from '~/common/redis/redis-v2'
import { Hub } from '~/types'
import { closeHub, createHub } from '~/utils/db/hub'

import { deleteKeysWithPrefix } from '../../cdp/_tests/redis'
import { PerIssueGuardedRateLimiterService } from './per-issue-guarded-rate-limiter.service'
import { defineLuaTokenBucketGuarded } from './redis-token-bucket-guarded.lua'

const mockNow: jest.SpyInstance = jest.spyOn(Date, 'now')

describe('PerIssueGuardedRateLimiterService', () => {
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

        redis = createRedisV2PoolFromConfig(
            {
                connection: hub.CDP_REDIS_HOST
                    ? {
                          url: hub.CDP_REDIS_HOST,
                          options: { port: hub.CDP_REDIS_PORT, password: hub.CDP_REDIS_PASSWORD },
                      }
                    : { url: hub.REDIS_URL },
                poolMinSize: hub.REDIS_POOL_MIN_SIZE,
                poolMaxSize: hub.REDIS_POOL_MAX_SIZE,
            },
            [defineLuaTokenBucketGuarded]
        )
    })

    afterEach(async () => {
        await closeHub(hub)
        jest.clearAllMocks()
    })

    const build = (
        name: string,
        overrides: Partial<{
            threshold: number
            windowTtlSeconds: number
            fallbackTtlSeconds: number
            bucketTtlSeconds: number
        }> = {}
    ) =>
        new PerIssueGuardedRateLimiterService(
            {
                name,
                threshold: overrides.threshold ?? 3,
                windowTtlSeconds: overrides.windowTtlSeconds ?? 3600,
                fallbackTtlSeconds: overrides.fallbackTtlSeconds ?? 300,
                bucketTtlSeconds: overrides.bucketTtlSeconds ?? 60 * 60 * 24,
            },
            redis
        )

    const cleanLimiter = async (limiter: PerIssueGuardedRateLimiterService) => {
        await deleteKeysWithPrefix(redis, limiter.getBucketKeyPrefix())
        await deleteKeysWithPrefix(redis, limiter.getCounterKeyPrefix())
        await deleteKeysWithPrefix(redis, limiter.getFallbackKeyPrefix())
    }

    const readCounter = async (key: string): Promise<number | null> => {
        const res = await redis.useClient({ name: 'read-counter' }, async (client) => client.get(key))
        return res == null ? null : Number(res)
    }

    const fallbackIsSet = async (key: string): Promise<boolean> => {
        const res = await redis.useClient({ name: 'read-fallback' }, async (client) => client.get(key))
        return res != null
    }

    const req = (
        teamId: number,
        sig: string,
        cost = 1,
        overrides: Partial<{ bucketSize: number; refillRate: number }> = {}
    ) => ({
        teamId,
        sig,
        cost,
        bucketSize: overrides.bucketSize ?? 100,
        refillRate: overrides.refillRate ?? 10,
    })

    it('allows the first new-sig event and bumps the per-team window counter', async () => {
        const limiter = build('first-event')
        await cleanLimiter(limiter)

        const res = await limiter.rateLimit([req(42, 'sig-a')])

        expect([...res.values()]).toEqual([expect.objectContaining({ status: 'allowed', isRateLimited: false })])
        const nowSeconds = Math.round(now / 1000)
        expect(await readCounter(limiter.counterKey(42, nowSeconds))).toBe(1)
        expect(await fallbackIsSet(limiter.fallbackKey(42))).toBe(false)
    })

    it('skips counter increment for an already-seen sig', async () => {
        const limiter = build('repeat-sig')
        await cleanLimiter(limiter)

        await limiter.rateLimit([req(42, 'sig-a')])
        await limiter.rateLimit([req(42, 'sig-a')])
        await limiter.rateLimit([req(42, 'sig-a')])

        const nowSeconds = Math.round(now / 1000)
        expect(await readCounter(limiter.counterKey(42, nowSeconds))).toBe(1)
    })

    it('trips the fallback flag when new-key creations exceed threshold', async () => {
        const limiter = build('trip-threshold', { threshold: 2 })
        await cleanLimiter(limiter)

        const r1 = await limiter.rateLimit([req(42, 'a')])
        const r2 = await limiter.rateLimit([req(42, 'b')])
        const r3 = await limiter.rateLimit([req(42, 'c')])

        expect([...r1.values()][0].status).toBe('allowed')
        expect([...r2.values()][0].status).toBe('allowed')
        // 3rd new sig pushes counter to 3 > threshold 2 → tripped.
        expect([...r3.values()][0].status).toBe('tripped')
        expect(await fallbackIsSet(limiter.fallbackKey(42))).toBe(true)
    })

    it('does not create the bucket key when tripped', async () => {
        const limiter = build('no-bucket-on-trip', { threshold: 1 })
        await cleanLimiter(limiter)

        await limiter.rateLimit([req(42, 'first')]) // allowed, bucket created
        const trippedResult = await limiter.rateLimit([req(42, 'second')]) // tripped, bucket NOT created
        expect([...trippedResult.values()][0].status).toBe('tripped')

        const bucketExists = await redis.useClient({ name: 'check' }, async (client) =>
            client.exists(limiter.bucketKey(42, 'second'))
        )
        expect(bucketExists).toBe(0)
    })

    it('short-circuits subsequent events on fallback', async () => {
        const limiter = build('short-circuit', { threshold: 1 })
        await cleanLimiter(limiter)

        await limiter.rateLimit([req(42, 'a')])
        await limiter.rateLimit([req(42, 'b')]) // trips
        const after = await limiter.rateLimit([req(42, 'c')])

        expect([...after.values()][0].status).toBe('fallback')
        // Counter should not have advanced past the trip value (no INCR during fallback).
        const nowSeconds = Math.round(now / 1000)
        expect(await readCounter(limiter.counterKey(42, nowSeconds))).toBe(2)
    })

    it('isolates fallback flags by team', async () => {
        const limiter = build('team-iso', { threshold: 1 })
        await cleanLimiter(limiter)

        // Team 42 trips.
        await limiter.rateLimit([req(42, 'a')])
        await limiter.rateLimit([req(42, 'b')])
        expect(await fallbackIsSet(limiter.fallbackKey(42))).toBe(true)

        // Team 99 is unaffected.
        const r = await limiter.rateLimit([req(99, 'a')])
        expect([...r.values()][0].status).toBe('allowed')
        expect(await fallbackIsSet(limiter.fallbackKey(99))).toBe(false)
    })

    it('rotates the counter on hour boundary while fallback persists', async () => {
        const limiter = build('hour-rotate', { threshold: 1, windowTtlSeconds: 3600 })
        await cleanLimiter(limiter)

        await limiter.rateLimit([req(42, 'a')])
        await limiter.rateLimit([req(42, 'b')]) // trips

        const nowSeconds = Math.round(now / 1000)
        const counterH = limiter.counterKey(42, nowSeconds)

        // Roll the clock forward into the next hour bucket.
        advanceTime(3600 * 1000)
        const counterHPlus1 = limiter.counterKey(42, Math.round(now / 1000))
        expect(counterHPlus1).not.toBe(counterH)

        // Still in fallback (5 min TTL not exhausted), so a new-sig event short-circuits.
        const r = await limiter.rateLimit([req(42, 'c')])
        expect([...r.values()][0].status).toBe('fallback')
        // New-hour counter is untouched while in fallback.
        expect(await readCounter(counterHPlus1)).toBeNull()
    })

    it('returns to allowed once fallback TTL expires and team stops creating new sigs', async () => {
        const limiter = build('recover', { threshold: 1, fallbackTtlSeconds: 1 })
        await cleanLimiter(limiter)

        await limiter.rateLimit([req(42, 'a')])
        await limiter.rateLimit([req(42, 'b')]) // trips
        expect(await fallbackIsSet(limiter.fallbackKey(42))).toBe(true)

        // Wait for the fallback flag to expire.
        await new Promise((resolve) => setTimeout(resolve, 1100))
        expect(await fallbackIsSet(limiter.fallbackKey(42))).toBe(false)

        // Repeat of an existing sig: bucket already exists, no INCR, no re-trip.
        const r = await limiter.rateLimit([req(42, 'a')])
        expect([...r.values()][0].status).toBe('allowed')
    })

    it('rate-limits when a single sig exceeds its own bucket', async () => {
        const limiter = build('bucket-limit')
        await cleanLimiter(limiter)

        // bucketSize=5 — second call of cost=4 will overshoot.
        await limiter.rateLimit([req(42, 'noisy', 4, { bucketSize: 5, refillRate: 0 })])
        const r = await limiter.rateLimit([req(42, 'noisy', 4, { bucketSize: 5, refillRate: 0 })])
        expect([...r.values()][0].status).toBe('limited')
        expect([...r.values()][0].isRateLimited).toBe(true)
    })

    it('fails open when the Redis pipeline fails', async () => {
        const limiter = new PerIssueGuardedRateLimiterService(
            {
                name: 'fail-open',
                threshold: 1,
                windowTtlSeconds: 3600,
                fallbackTtlSeconds: 60,
                bucketTtlSeconds: 60,
            },
            {
                useClient: jest.fn(),
                usePipeline: jest.fn().mockResolvedValue(null),
            } as unknown as RedisV2
        )

        const res = await limiter.rateLimit([req(42, 'a'), req(42, 'b')])
        for (const r of res.values()) {
            expect(r).toEqual(expect.objectContaining({ status: 'allowed', isRateLimited: false }))
        }
    })
})
