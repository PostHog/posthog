import { register } from 'prom-client'

import { defaultConfig } from '~/common/config/config'
import { deleteKeysWithPrefix } from '~/common/redis/_tests/redis'
import { RedisV2, createRedisV2PoolFromConfig } from '~/common/redis/redis-v2'
import { KeyedRateLimitRequest } from '~/common/services/keyed-rate-limiter.service'
import { logger } from '~/common/utils/logger'

import { PerIssueGuardedRateLimiterService } from './per-issue-guarded-rate-limiter.service'

const mockNow: jest.SpyInstance = jest.spyOn(Date, 'now')

describe('PerIssueGuardedRateLimiterService', () => {
    jest.retryTimes(3)

    let now: number
    let redis: RedisV2

    const advanceTime = (ms: number) => {
        now += ms
        mockNow.mockReturnValue(now)
    }

    beforeEach(() => {
        now = 1720000000000
        mockNow.mockReturnValue(now)

        redis = createRedisV2PoolFromConfig({
            connection: defaultConfig.CDP_REDIS_HOST
                ? {
                      url: defaultConfig.CDP_REDIS_HOST,
                      options: { port: defaultConfig.CDP_REDIS_PORT, password: defaultConfig.CDP_REDIS_PASSWORD },
                  }
                : { url: defaultConfig.REDIS_URL },
            poolMinSize: defaultConfig.REDIS_POOL_MIN_SIZE,
            poolMaxSize: defaultConfig.REDIS_POOL_MAX_SIZE,
        })
    })

    afterEach(() => {
        jest.clearAllMocks()
    })

    const build = (
        name: string,
        overrides: Partial<{
            threshold: number
            windowTtlSeconds: number
            cooldownTtlSeconds: number
            bucketTtlSeconds: number
        }> = {}
    ) =>
        new PerIssueGuardedRateLimiterService(
            {
                name,
                threshold: overrides.threshold ?? 3,
                windowTtlSeconds: overrides.windowTtlSeconds ?? 3600,
                cooldownTtlSeconds: overrides.cooldownTtlSeconds ?? 300,
                bucketTtlSeconds: overrides.bucketTtlSeconds ?? 60 * 60 * 24,
            },
            redis
        )

    const cleanLimiter = async (limiter: PerIssueGuardedRateLimiterService) => {
        await deleteKeysWithPrefix(redis, limiter.getKeyPrefix())
        await deleteKeysWithPrefix(redis, limiter.getCounterKeyPrefix())
        await deleteKeysWithPrefix(redis, limiter.getCooldownKeyPrefix())
    }

    const readCounter = async (key: string): Promise<number | null> => {
        const res = await redis.useClient({ name: 'read-counter' }, async (client) => client.get(key))
        return res == null ? null : Number(res)
    }

    const cooldownIsSet = async (key: string): Promise<boolean> => {
        const res = await redis.useClient({ name: 'read-cooldown' }, async (client) => client.get(key))
        return res != null
    }

    const req = (
        teamId: number,
        scopeKey: string,
        cost = 1,
        overrides: Partial<{ bucketSize: number; refillRate: number }> = {}
    ): KeyedRateLimitRequest => ({
        id: `${teamId}:exceptions:issue:${scopeKey}`,
        teamId,
        cost,
        bucketSize: overrides.bucketSize ?? 100,
        refillRate: overrides.refillRate ?? 10,
    })

    const outcomeCount = async (outcome: string): Promise<number> => {
        const metrics = await register.getMetricsAsJSON()
        const metric = metrics.find((m) => m.name === 'error_tracking_per_issue_guard_outcome_total')
        return metric?.values.find((v) => v.labels.outcome === outcome)?.value ?? 0
    }

    const buildWithPipelineResult = (result: unknown): PerIssueGuardedRateLimiterService =>
        new PerIssueGuardedRateLimiterService(
            { name: 'lua-fail', threshold: 1, windowTtlSeconds: 3600, cooldownTtlSeconds: 60, bucketTtlSeconds: 60 },
            { useClient: jest.fn(), usePipeline: jest.fn().mockResolvedValue(result) } as unknown as RedisV2
        )

    it('allows the first event with a new scopeKey and bumps the per-team window counter', async () => {
        const limiter = build('first-event')
        await cleanLimiter(limiter)

        const res = await limiter.rateLimitGrouped([req(42, 'scope-a')])

        expect(res[0][1]).toEqual(expect.objectContaining({ isRateLimited: false }))
        const nowSeconds = Math.round(now / 1000)
        expect(await readCounter(limiter.counterKey(42, nowSeconds))).toBe(1)
        expect(await cooldownIsSet(limiter.cooldownKey(42))).toBe(false)
    })

    it('colocates cooldown, counter, and bucket keys on one Redis Cluster slot per team', () => {
        const limiter = build('slot-tag')
        const nowSeconds = Math.round(now / 1000)
        const keys = [
            limiter.cooldownKey(42),
            limiter.counterKey(42, nowSeconds),
            limiter.bucketKey(42, '42:exceptions:issue:abc'),
        ]
        // Redis hashes only the substring inside the first {…}; identical tags ⇒ same slot ⇒ no CROSSSLOT.
        const hashTag = (key: string) => key.slice(key.indexOf('{') + 1, key.indexOf('}'))
        expect(keys.map(hashTag)).toEqual(['42', '42', '42'])
        // Different teams must not collapse onto the same tag.
        expect(hashTag(limiter.cooldownKey(99))).toBe('99')
    })

    it('skips counter increment for an already-seen scopeKey', async () => {
        const limiter = build('repeat-scope')
        await cleanLimiter(limiter)

        await limiter.rateLimitGrouped([req(42, 'scope-a')])
        await limiter.rateLimitGrouped([req(42, 'scope-a')])
        await limiter.rateLimitGrouped([req(42, 'scope-a')])

        const nowSeconds = Math.round(now / 1000)
        expect(await readCounter(limiter.counterKey(42, nowSeconds))).toBe(1)
    })

    it('does not create the bucket key once tripped, and short-circuits subsequent events', async () => {
        const limiter = build('trip', { threshold: 1 })
        await cleanLimiter(limiter)

        const r1 = await limiter.rateLimitGrouped([req(42, 'a')]) // allowed (counter=1)
        const r2 = await limiter.rateLimitGrouped([req(42, 'b')]) // tripped (counter=2 > threshold 1)
        const r3 = await limiter.rateLimitGrouped([req(42, 'c')]) // cooldown (flag set)

        // r1 mints a bucket, r2/r3 do not (per-issue defers to team-global → isRateLimited=false).
        expect(r1[0][1].isRateLimited).toBe(false)
        expect(r2[0][1].isRateLimited).toBe(false)
        expect(r3[0][1].isRateLimited).toBe(false)
        expect(await cooldownIsSet(limiter.cooldownKey(42))).toBe(true)

        // Bucket for 'b' was never written.
        const bExists = await redis.useClient({ name: 'check' }, async (client) =>
            client.exists(limiter.bucketKey(42, '42:exceptions:issue:b'))
        )
        expect(bExists).toBe(0)

        // Counter stayed at 2 — no INCR during cooldown.
        const nowSeconds = Math.round(now / 1000)
        expect(await readCounter(limiter.counterKey(42, nowSeconds))).toBe(2)
    })

    it('isolates cooldown flags by team', async () => {
        const limiter = build('team-iso', { threshold: 1 })
        await cleanLimiter(limiter)

        await limiter.rateLimitGrouped([req(42, 'a')])
        await limiter.rateLimitGrouped([req(42, 'b')])
        expect(await cooldownIsSet(limiter.cooldownKey(42))).toBe(true)

        const r = await limiter.rateLimitGrouped([req(99, 'a')])
        expect(r[0][1].isRateLimited).toBe(false)
        expect(await cooldownIsSet(limiter.cooldownKey(99))).toBe(false)
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

        // After the rollover, the new-hour counter starts fresh on the next new scopeKey.
        await limiter.rateLimitGrouped([req(42, 'b')])
        expect(await readCounter(counterHPlus1)).toBe(1)
    })

    it('returns to allowed once cooldown TTL expires and team stops creating new scopeKeys', async () => {
        const limiter = build('recover', { threshold: 1, cooldownTtlSeconds: 1 })
        await cleanLimiter(limiter)

        await limiter.rateLimitGrouped([req(42, 'a')])
        await limiter.rateLimitGrouped([req(42, 'b')])
        expect(await cooldownIsSet(limiter.cooldownKey(42))).toBe(true)

        await new Promise((resolve) => setTimeout(resolve, 1100))
        expect(await cooldownIsSet(limiter.cooldownKey(42))).toBe(false)

        const r = await limiter.rateLimitGrouped([req(42, 'a')])
        expect(r[0][1].isRateLimited).toBe(false)
    })

    it('rate-limits when a single scopeKey drains its own bucket', async () => {
        const limiter = build('bucket-limit')
        await cleanLimiter(limiter)

        await limiter.rateLimitGrouped([req(42, 'noisy', 4, { bucketSize: 5, refillRate: 0 })])
        const r = await limiter.rateLimitGrouped([req(42, 'noisy', 4, { bucketSize: 5, refillRate: 0 })])
        expect(r[0][1].isRateLimited).toBe(true)
    })

    it('allows the first N inputs of an over-budget single-scopeKey batch and denies the rest', async () => {
        const limiter = build('partial-passthrough')
        await cleanLimiter(limiter)

        // bucketSize 3, refillRate 0 — five inputs sharing one scopeKey: first 3 pass, last 2 limited.
        const requests = Array.from({ length: 5 }, () => req(42, 'shared', 1, { bucketSize: 3, refillRate: 0 }))
        const res = await limiter.rateLimitGrouped(requests)

        expect(res.map(([, r]) => r.isRateLimited)).toEqual([false, false, false, true, true])
    })

    it('handles a mixed batch: cooldown team, tripping team, partial pass-through, clean team', async () => {
        const limiter = build('big-mix', { threshold: 2 })
        await cleanLimiter(limiter)

        const bucketExists = async (key: string): Promise<number> =>
            (await redis.useClient({ name: 'check' }, async (client) => client.exists(key))) ?? 0

        // Pre-trip team 100: 3 new scopeKeys against threshold=2 → cooldown flag set.
        await limiter.rateLimitGrouped([req(100, 'pre1'), req(100, 'pre2'), req(100, 'pre3')])
        expect(await cooldownIsSet(limiter.cooldownKey(100))).toBe(true)

        // Single big batch covering every status at once:
        //   team 100: already in cooldown → both events pass through, no buckets minted.
        //   team 200: 3 distinct scopeKeys → first 2 allowed, third trips.
        //   team 300: 4 inputs sharing one scopeKey, bucket=2 → first 2 allowed, last 2 limited.
        //   team 400: 2 distinct scopeKeys → both clean pass, no trip (counter 2 == threshold).
        const batch = [
            req(100, 'cooldown-1'),
            req(100, 'cooldown-2'),
            req(200, 'tripA'),
            req(200, 'tripB'),
            req(200, 'tripC'),
            req(300, 'noisy', 1, { bucketSize: 2, refillRate: 0 }),
            req(300, 'noisy', 1, { bucketSize: 2, refillRate: 0 }),
            req(300, 'noisy', 1, { bucketSize: 2, refillRate: 0 }),
            req(300, 'noisy', 1, { bucketSize: 2, refillRate: 0 }),
            req(400, 'cleanA'),
            req(400, 'cleanB'),
        ]
        const res = await limiter.rateLimitGrouped(batch)

        expect(res.map(([, r]) => r.isRateLimited)).toEqual([
            false, // 100 cooldown
            false, // 100 cooldown
            false, // 200 allowed
            false, // 200 allowed
            false, // 200 tripped (passes through)
            false, // 300 allowed (budget 2 → 1)
            false, // 300 allowed (budget 1 → 0)
            true, // 300 limited
            true, // 300 limited
            false, // 400 allowed
            false, // 400 allowed
        ])

        // Team 100 was already in cooldown → new scopeKeys never minted buckets.
        expect(await bucketExists(limiter.bucketKey(100, '100:exceptions:issue:cooldown-1'))).toBe(0)
        expect(await bucketExists(limiter.bucketKey(100, '100:exceptions:issue:cooldown-2'))).toBe(0)

        // Team 200 tripped this batch — first two buckets minted, third (tripC) NOT.
        expect(await cooldownIsSet(limiter.cooldownKey(200))).toBe(true)
        expect(await bucketExists(limiter.bucketKey(200, '200:exceptions:issue:tripA'))).toBe(1)
        expect(await bucketExists(limiter.bucketKey(200, '200:exceptions:issue:tripB'))).toBe(1)
        expect(await bucketExists(limiter.bucketKey(200, '200:exceptions:issue:tripC'))).toBe(0)

        // Team 300 never tripped (only 1 distinct scopeKey).
        expect(await cooldownIsSet(limiter.cooldownKey(300))).toBe(false)
        // Team 400 stayed under threshold.
        expect(await cooldownIsSet(limiter.cooldownKey(400))).toBe(false)
    })

    it('throws when a request is missing teamId', async () => {
        const limiter = build('missing-team')
        await cleanLimiter(limiter)

        await expect(
            limiter.rateLimitGrouped([{ id: 'whatever', cost: 1, bucketSize: 100, refillRate: 1 }])
        ).rejects.toThrow(/missing teamId/)
    })

    it('fails open when the Redis pipeline fails', async () => {
        const limiter = new PerIssueGuardedRateLimiterService(
            {
                name: 'fail-open',
                threshold: 1,
                windowTtlSeconds: 3600,
                cooldownTtlSeconds: 60,
                bucketTtlSeconds: 60,
            },
            {
                useClient: jest.fn(),
                usePipeline: jest.fn().mockResolvedValue(null),
            } as unknown as RedisV2
        )

        const before = await outcomeCount('fail_open_redis')
        const res = await limiter.rateLimitGrouped([req(42, 'a'), req(42, 'b')])
        for (const [, r] of res) {
            expect(r).toEqual(expect.objectContaining({ isRateLimited: false }))
        }
        expect((await outcomeCount('fail_open_redis')) - before).toBe(2)
    })

    it('warns and records fail_open_lua when a single Lua call errored', async () => {
        const warnSpy = jest.spyOn(logger, 'warn')
        const before = await outcomeCount('fail_open_lua')
        const limiter = buildWithPipelineResult([[new Error('lua boom'), null]])

        const res = await limiter.rateLimitGrouped([req(42, 'a')])

        expect(res[0][1]).toEqual(expect.objectContaining({ isRateLimited: false }))
        expect(warnSpy).toHaveBeenCalledTimes(1)
        expect((await outcomeCount('fail_open_lua')) - before).toBe(1)
    })

    it.each([
        ['wrong tuple size', [10]],
        ['non-numeric values', ['x', 'y', 'z']],
        ['null reply', null],
    ])('warns and records fail_open_lua when the Lua reply is malformed (%s)', async (_label, value) => {
        const warnSpy = jest.spyOn(logger, 'warn')
        const before = await outcomeCount('fail_open_lua')
        const limiter = buildWithPipelineResult([[null, value]])

        const res = await limiter.rateLimitGrouped([req(42, 'a')])

        expect(res[0][1]).toEqual(expect.objectContaining({ isRateLimited: false }))
        expect(warnSpy).toHaveBeenCalledTimes(1)
        expect((await outcomeCount('fail_open_lua')) - before).toBe(1)
    })
})
