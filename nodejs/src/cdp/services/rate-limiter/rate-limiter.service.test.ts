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
            expect(claim).toEqual({ granted: true, deniedIndex: null, retryAfterMs: null })
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
            expect(claim).toEqual({ granted: false, deniedIndex: 1, retryAfterMs: null })
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
            expect(claim).toEqual({ granted: false, deniedIndex: 1, retryAfterMs: 10_000 })
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
            expect(claim).toEqual({ granted: false, deniedIndex: 0, retryAfterMs: 40_000 })
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
            expect(claim).toEqual({ granted: false, deniedIndex: null, retryAfterMs: null })
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
            // Each of these slots is the caller's alone, which is what lets the caller park on
            // it as given instead of spreading its wake and closing the gap to the caller ahead.
            expect([first.reserved, second.reserved, third.reserved]).toEqual([true, true, true])
        })

        it('charges the first denial only for the tokens the bucket is short of', async () => {
            // Capacity 1 at 0.25 tokens/s, so a whole token interval is 4s. Drain, then let
            // part of a token accrue. The reserved slot must be the shortfall, not the full
            // interval: the accrued part is credit already earned, and waiting the interval out
            // also lets accrual run past a capacity of 1, where the cap throws the surplus away.
            const partialReq = { key: `${RESERVE_KEY}/partial`, requested: 1, capacity: 1, refillPerSecond: 0.25 }
            await limiter.claimUpTo(partialReq)
            await new Promise((resolve) => setTimeout(resolve, 1_000))

            const denial = await limiter.claimOrReserve(partialReq, 60_000)

            expect(denial.granted).toBe(0)
            expect(denial.reserved).toBe(true)
            // The slot is 4s minus whatever accrued during the wait, so a runner that oversleeps
            // only shortens it. Charging the full interval would report 4s and fail here.
            expect(denial.retryAfterMs).toBeGreaterThan(0)
            expect(denial.retryAfterMs).toBeLessThanOrEqual(3_000)
        })

        it('stops advancing the cursor at the horizon', async () => {
            // Slot interval 1s with a 1s horizon: the first denial can reserve the one
            // slot inside the horizon; everyone after gets the horizon back unchanged
            // (and un-reserved), so a deep backlog re-contends there instead of the
            // cursor running away.
            const slowReq = { key: `${RESERVE_KEY}/capped`, requested: 1, capacity: 1, refillPerSecond: 1 }
            await limiter.claimUpTo({ ...slowReq })

            const first = await limiter.claimOrReserve(slowReq, 1_000)
            const second = await limiter.claimOrReserve(slowReq, 1_000)
            const third = await limiter.claimOrReserve(slowReq, 1_000)

            expect(first.retryAfterMs).toBeLessThanOrEqual(1_000)
            expect(second.retryAfterMs).toBe(1_000)
            expect(third.retryAfterMs).toBe(1_000)
            // Only the first held a slot. The other two share one wake time, so they report
            // `reserved: false` and the caller knows to spread them itself.
            expect([first.reserved, second.reserved, third.reserved]).toEqual([true, false, false])
        })
    })
})
