import { RedisV2, createRedisV2PoolFromConfig } from '~/common/redis/redis-v2'
import { KeyedRateLimitRequest } from '~/common/services/keyed-rate-limiter.service'
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
        await deleteKeysWithPrefix(redis, limiter.getKeyPrefix())
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
    ): KeyedRateLimitRequest => ({
        id: `${teamId}:exceptions:issue:${sig}`,
        cost,
        bucketSize: overrides.bucketSize ?? 100,
        refillRate: overrides.refillRate ?? 10,
    })

    it('allows the first new-sig event and bumps the per-team window counter', async () => {
        const limiter = build('first-event')
        await cleanLimiter(limiter)

        const res = await limiter.rateLimitGrouped([req(42, 'sig-a')])

        expect(res[0][1]).toEqual(expect.objectContaining({ isRateLimited: false }))
        const nowSeconds = Math.round(now / 1000)
        expect(await readCounter(limiter.counterKey(42, nowSeconds))).toBe(1)
        expect(await fallbackIsSet(limiter.fallbackKey(42))).toBe(false)
    })

    it('skips counter increment for an already-seen sig', async () => {
        const limiter = build('repeat-sig')
        await cleanLimiter(limiter)

        await limiter.rateLimitGrouped([req(42, 'sig-a')])
        await limiter.rateLimitGrouped([req(42, 'sig-a')])
        await limiter.rateLimitGrouped([req(42, 'sig-a')])

        const nowSeconds = Math.round(now / 1000)
        expect(await readCounter(limiter.counterKey(42, nowSeconds))).toBe(1)
    })

    it('does not create the bucket key once tripped, and short-circuits subsequent events', async () => {
        const limiter = build('trip', { threshold: 1 })
        await cleanLimiter(limiter)

        const r1 = await limiter.rateLimitGrouped([req(42, 'a')]) // allowed (counter=1)
        const r2 = await limiter.rateLimitGrouped([req(42, 'b')]) // tripped (counter=2 > threshold 1)
        const r3 = await limiter.rateLimitGrouped([req(42, 'c')]) // fallback (flag set)

        // r1 mints a bucket, r2/r3 do not (per-issue defers to team-global → isRateLimited=false).
        expect(r1[0][1].isRateLimited).toBe(false)
        expect(r2[0][1].isRateLimited).toBe(false)
        expect(r3[0][1].isRateLimited).toBe(false)
        expect(await fallbackIsSet(limiter.fallbackKey(42))).toBe(true)

        // Bucket for 'b' was never written.
        const bExists = await redis.useClient({ name: 'check' }, async (client) =>
            client.exists(`${limiter.getKeyPrefix()}/42:exceptions:issue:b`)
        )
        expect(bExists).toBe(0)

        // Counter stayed at 2 — no INCR during fallback.
        const nowSeconds = Math.round(now / 1000)
        expect(await readCounter(limiter.counterKey(42, nowSeconds))).toBe(2)
    })

    it('isolates fallback flags by team', async () => {
        const limiter = build('team-iso', { threshold: 1 })
        await cleanLimiter(limiter)

        await limiter.rateLimitGrouped([req(42, 'a')])
        await limiter.rateLimitGrouped([req(42, 'b')])
        expect(await fallbackIsSet(limiter.fallbackKey(42))).toBe(true)

        const r = await limiter.rateLimitGrouped([req(99, 'a')])
        expect(r[0][1].isRateLimited).toBe(false)
        expect(await fallbackIsSet(limiter.fallbackKey(99))).toBe(false)
    })

    it('rotates the counter on hour boundary', async () => {
        const limiter = build('hour-rotate', { threshold: 1, windowTtlSeconds: 3600 })
        await cleanLimiter(limiter)

        await limiter.rateLimitGrouped([req(42, 'a')])

        const nowSeconds = Math.round(now / 1000)
        const counterH = limiter.counterKey(42, nowSeconds)
        advanceTime(3600 * 1000)
        const counterHPlus1 = limiter.counterKey(42, Math.round(now / 1000))
        expect(counterHPlus1).not.toBe(counterH)

        // After the rollover, the new-hour counter starts fresh on the next new sig.
        await limiter.rateLimitGrouped([req(42, 'b')])
        expect(await readCounter(counterHPlus1)).toBe(1)
    })

    it('returns to allowed once fallback TTL expires and team stops creating new sigs', async () => {
        const limiter = build('recover', { threshold: 1, fallbackTtlSeconds: 1 })
        await cleanLimiter(limiter)

        await limiter.rateLimitGrouped([req(42, 'a')])
        await limiter.rateLimitGrouped([req(42, 'b')])
        expect(await fallbackIsSet(limiter.fallbackKey(42))).toBe(true)

        await new Promise((resolve) => setTimeout(resolve, 1100))
        expect(await fallbackIsSet(limiter.fallbackKey(42))).toBe(false)

        const r = await limiter.rateLimitGrouped([req(42, 'a')])
        expect(r[0][1].isRateLimited).toBe(false)
    })

    it('rate-limits when a single sig drains its own bucket', async () => {
        const limiter = build('bucket-limit')
        await cleanLimiter(limiter)

        await limiter.rateLimitGrouped([req(42, 'noisy', 4, { bucketSize: 5, refillRate: 0 })])
        const r = await limiter.rateLimitGrouped([req(42, 'noisy', 4, { bucketSize: 5, refillRate: 0 })])
        expect(r[0][1].isRateLimited).toBe(true)
    })

    it('throws when the id does not match the expected format', async () => {
        const limiter = build('bad-id')
        await cleanLimiter(limiter)

        await expect(
            limiter.rateLimitGrouped([{ id: 'not-a-valid-id', cost: 1, bucketSize: 100, refillRate: 1 }])
        ).rejects.toThrow(/does not match the expected/)
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

        const res = await limiter.rateLimitGrouped([req(42, 'a'), req(42, 'b')])
        for (const [, r] of res) {
            expect(r).toEqual(expect.objectContaining({ isRateLimited: false }))
        }
    })
})
