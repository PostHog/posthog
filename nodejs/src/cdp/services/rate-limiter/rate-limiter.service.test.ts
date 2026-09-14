import { randomUUID } from 'crypto'
import { register } from 'prom-client'

import { deleteKeysWithPrefix } from '~/common/redis/_tests/redis'
import { RedisV2, createRedisV2PoolFromConfig } from '~/common/redis/redis-v2'
import { closeHub, createHub } from '~/common/utils/db/hub'
import { Hub } from '~/types'

import { RateLimiterService } from './rate-limiter.service'

const KEY = `@posthog-test/ses-rate-limiter/${randomUUID()}/bucket`

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
        await deleteKeysWithPrefix(redis, KEY)
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
            const labels = { limiter: 'ses-rate-limiter', result: 'granted_full' }
            const before = await readCounter(labels)

            const granted = await limiter.claimUpTo({ key: KEY, requested: 5, capacity: 10, refillPerSecond: 0 })
            expect(granted).toBe(5)

            const after = await readCounter(labels)
            expect(after - before).toBe(1)
        })

        it('increments granted_partial when the grant is less than the request', async () => {
            // Drain to 2 tokens, then ask for 5.
            await limiter.claimUpTo({ key: KEY, requested: 8, capacity: 10, refillPerSecond: 0 })

            const labels = { limiter: 'ses-rate-limiter', result: 'granted_partial' }
            const before = await readCounter(labels)

            const granted = await limiter.claimUpTo({ key: KEY, requested: 5, capacity: 10, refillPerSecond: 0 })
            expect(granted).toBe(2)

            const after = await readCounter(labels)
            expect(after - before).toBe(1)
        })

        it('increments denied when the bucket is empty', async () => {
            // Drain the bucket fully.
            await limiter.claimUpTo({ key: KEY, requested: 10, capacity: 10, refillPerSecond: 0 })

            const labels = { limiter: 'ses-rate-limiter', result: 'denied' }
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

            const labels = { limiter: 'broken-limiter', result: 'valkey_error' }
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

    describe('claimAllOrNothingPair', () => {
        const KEY_A = `${KEY}/pair-a`
        const KEY_B = `${KEY}/pair-b`

        it('grants from both buckets when both can cover the request', async () => {
            const claim = await limiter.claimAllOrNothingPair(
                [
                    { key: KEY_A, capacity: 50, refillPerSecond: 0 },
                    { key: KEY_B, capacity: 100, refillPerSecond: 0 },
                ],
                30
            )
            expect(claim).toEqual({ granted: true, deniedIndex: null, retryAfterMs: null, reserved: false })
            // Both pools were charged: the remainder is all that is left to claim.
            expect(await limiter.claimUpTo({ key: KEY_A, requested: 50, capacity: 50, refillPerSecond: 0 })).toBe(20)
            expect(await limiter.claimUpTo({ key: KEY_B, requested: 100, capacity: 100, refillPerSecond: 0 })).toBe(70)
        })

        it('consumes nothing on denial, so retries cannot starve the buckets', async () => {
            // The second bucket cannot cover the request, so the claim must leave BOTH pools
            // untouched. Without that, a rescheduled multi-recipient send would burn the first
            // bucket's refill on every retry while never sending.
            const claim = await limiter.claimAllOrNothingPair(
                [
                    { key: KEY_A, capacity: 50, refillPerSecond: 0 },
                    { key: KEY_B, capacity: 10, refillPerSecond: 0 },
                ],
                30
            )
            // refillPerSecond 0 means the missing tokens never accrue, so no horizon is reported.
            expect(claim).toEqual({ granted: false, deniedIndex: 1, retryAfterMs: null, reserved: false })
            expect(await limiter.claimUpTo({ key: KEY_A, requested: 50, capacity: 50, refillPerSecond: 0 })).toBe(50)
            expect(await limiter.claimUpTo({ key: KEY_B, requested: 10, capacity: 10, refillPerSecond: 0 })).toBe(10)
        })

        it('reports on denial how long until the missing tokens accrue', async () => {
            // Cold start: the denying bucket holds exactly its capacity of 10, so the request
            // for 30 is missing 20 tokens. At 2 tokens/s that is 10 seconds.
            const claim = await limiter.claimAllOrNothingPair(
                [
                    { key: KEY_A, capacity: 50, refillPerSecond: 0 },
                    { key: KEY_B, capacity: 10, refillPerSecond: 2 },
                ],
                30
            )
            expect(claim).toEqual({ granted: false, deniedIndex: 1, retryAfterMs: 10_000, reserved: false })
        })

        it('reports the slower bucket when both are short', async () => {
            // Both buckets are 20 tokens short of the request. The first one covers that in 10
            // seconds, the second needs 40. Reporting the first would wake the caller while the
            // second still cannot grant, costing a whole extra dequeue and reschedule.
            const claim = await limiter.claimAllOrNothingPair(
                [
                    { key: KEY_A, capacity: 10, refillPerSecond: 2 },
                    { key: KEY_B, capacity: 10, refillPerSecond: 0.5 },
                ],
                30
            )
            expect(claim).toEqual({ granted: false, deniedIndex: 0, retryAfterMs: 40_000, reserved: false })
        })

        it('fails closed when the Lua call throws', async () => {
            const brokenValkey = {
                useClient: jest.fn().mockRejectedValue(new Error('connection lost')),
                usePipeline: jest.fn(),
            } as unknown as RedisV2
            const brokenLimiter = new RateLimiterService(brokenValkey, { name: 'broken-limiter' })
            const claim = await brokenLimiter.claimAllOrNothingPair(
                [
                    { key: KEY_A, capacity: 50, refillPerSecond: 0 },
                    { key: KEY_B, capacity: 10, refillPerSecond: 0 },
                ],
                5
            )
            expect(claim).toEqual({ granted: false, deniedIndex: null, retryAfterMs: null, reserved: false })
        })

        it('hands successive reserved denials distinct, later slots, paced by the slower bucket', async () => {
            // Both buckets are short, so the slower one (0.5/s) sets the pace. The first
            // caller waits 40s (its missing tokens). The next one gets the slot after
            // that, a full 60s later. Nobody wakes at the same time.
            const buckets: [
                { key: string; capacity: number; refillPerSecond: number },
                { key: string; capacity: number; refillPerSecond: number },
            ] = [
                { key: `${KEY_A}/resv`, capacity: 10, refillPerSecond: 2 },
                { key: `${KEY_B}/resv`, capacity: 10, refillPerSecond: 0.5 },
            ]
            const first = await limiter.claimAllOrNothingPair(buckets, 30, 600_000)
            const second = await limiter.claimAllOrNothingPair(buckets, 30, 600_000)

            expect(first.granted).toBe(false)
            expect(first.reserved).toBe(true)
            // First in line pays only the 40s shortfall, not a full 60s slot.
            expect(first.retryAfterMs).toBe(40_000)
            expect(second.reserved).toBe(true)
            expect(second.retryAfterMs!).toBeGreaterThan(first.retryAfterMs!)
            expect(second.retryAfterMs!).toBeLessThanOrEqual(100_000)
        })

        it('stops advancing the reservation cursor at the horizon', async () => {
            const buckets: [
                { key: string; capacity: number; refillPerSecond: number },
                { key: string; capacity: number; refillPerSecond: number },
            ] = [
                { key: `${KEY_A}/resv-cap`, capacity: 50, refillPerSecond: 0 },
                { key: `${KEY_B}/resv-cap`, capacity: 10, refillPerSecond: 2 },
            ]
            // The first slot (10s) fits inside the 20s horizon. The next one would not,
            // so everyone after the first just gets "come back in 20s" with no slot.
            const first = await limiter.claimAllOrNothingPair(buckets, 30, 20_000)
            const second = await limiter.claimAllOrNothingPair(buckets, 30, 20_000)
            const third = await limiter.claimAllOrNothingPair(buckets, 30, 20_000)

            expect(first.retryAfterMs).toBe(10_000)
            expect(first.reserved).toBe(true)
            expect(second.retryAfterMs).toBe(20_000)
            expect(second.reserved).toBe(false)
            expect(third.retryAfterMs).toBe(20_000)
            expect(third.reserved).toBe(false)
        })

        it('keeps one reservation line when the slower bucket changes', async () => {
            const buckets: [
                { key: string; capacity: number; refillPerSecond: number },
                { key: string; capacity: number; refillPerSecond: number },
            ] = [
                { key: `${KEY_A}/line`, capacity: 10, refillPerSecond: 2 },
                { key: `${KEY_B}/line`, capacity: 100, refillPerSecond: 0.5 },
            ]
            // The second bucket still covers the request, so the first one (10s
            // shortfall, 15s spacing) sets the pace for the first two denials.
            const first = await limiter.claimAllOrNothingPair(buckets, 30, 600_000)
            const second = await limiter.claimAllOrNothingPair(buckets, 30, 600_000)

            // Now drain the second bucket so it becomes the slower one. The line has
            // to continue behind the parked sends. A cursor kept only on the bucket
            // that is currently slower would start a fresh line here and hand this
            // send a slot at ~16s, ahead of the send already parked at ~25s.
            await limiter.claimUpTo({ key: buckets[1].key, requested: 78, capacity: 100, refillPerSecond: 0.5 })
            const third = await limiter.claimAllOrNothingPair(buckets, 30, 600_000)

            expect(first.reserved).toBe(true)
            expect(second.retryAfterMs!).toBeGreaterThan(first.retryAfterMs!)
            expect(third.reserved).toBe(true)
            expect(third.retryAfterMs!).toBeGreaterThan(second.retryAfterMs!)
        })
    })

    describe('claimOrReserve', () => {
        const RESERVE_KEY = `${KEY}/reserve`
        const req = { key: RESERVE_KEY, requested: 1, capacity: 2, refillPerSecond: 2 }

        it('grants normally without reserving a slot', async () => {
            const claim = await limiter.claimOrReserve(req, 60_000)
            expect(claim).toEqual({ granted: 1, retryAfterMs: null, reserved: false })
        })

        it('hands successive denials distinct, later slots', async () => {
            // Drain the bucket so every claim below is a full denial. At 2 tokens/s each
            // reservation advances the slot cursor by 500ms, so three denied callers park
            // at three different times instead of all retrying against the next token.
            await limiter.claimUpTo({ ...req, requested: 2 })

            const first = await limiter.claimOrReserve(req, 60_000)
            const second = await limiter.claimOrReserve(req, 60_000)
            const third = await limiter.claimOrReserve(req, 60_000)

            expect(first.granted).toBe(0)
            expect(first.retryAfterMs).toBeGreaterThan(0)
            // Strictly later each time; the spacing is ~500ms minus wall-clock elapsed
            // between calls, so bound it loosely rather than exactly.
            expect(second.retryAfterMs!).toBeGreaterThan(first.retryAfterMs!)
            expect(third.retryAfterMs!).toBeGreaterThan(second.retryAfterMs!)
            expect(third.retryAfterMs!).toBeLessThanOrEqual(1_500)
            // All three got their own slot, so each can park on it exactly.
            expect([first.reserved, second.reserved, third.reserved]).toEqual([true, true, true])
        })

        it('charges the first denial only for the tokens the bucket is short of', async () => {
            // One token takes 4s to refill. Drain the bucket, wait 1s so a quarter of a
            // token is back, then get denied. The slot must only cover what is still
            // missing (~3s), not the full 4s: the quarter token is credit already earned.
            const partialReq = { key: `${RESERVE_KEY}/partial`, requested: 1, capacity: 1, refillPerSecond: 0.25 }
            await limiter.claimUpTo(partialReq)
            await new Promise((resolve) => setTimeout(resolve, 1_000))

            const denial = await limiter.claimOrReserve(partialReq, 60_000)

            expect(denial.granted).toBe(0)
            expect(denial.reserved).toBe(true)
            // A slow test runner only makes the slot shorter (more refill happened).
            // Charging the full interval would report 4s and fail this bound.
            expect(denial.retryAfterMs).toBeGreaterThan(0)
            expect(denial.retryAfterMs).toBeLessThanOrEqual(3_000)
        })

        it('stops advancing the cursor at the horizon', async () => {
            // One 1s slot fits the 1s horizon. The first denial takes it; everyone after
            // just gets "come back in 1s" with no slot, so the cursor cannot run away.
            const slowReq = { key: `${RESERVE_KEY}/capped`, requested: 1, capacity: 1, refillPerSecond: 1 }
            await limiter.claimUpTo({ ...slowReq })

            const first = await limiter.claimOrReserve(slowReq, 1_000)
            const second = await limiter.claimOrReserve(slowReq, 1_000)
            const third = await limiter.claimOrReserve(slowReq, 1_000)

            expect(first.retryAfterMs).toBeLessThanOrEqual(1_000)
            expect(second.retryAfterMs).toBe(1_000)
            expect(third.retryAfterMs).toBe(1_000)
            // Only the first got a slot. The other two share one wake time and are told so,
            // which is the caller's cue to spread its own wake.
            expect([first.reserved, second.reserved, third.reserved]).toEqual([true, false, false])
        })
    })
})
