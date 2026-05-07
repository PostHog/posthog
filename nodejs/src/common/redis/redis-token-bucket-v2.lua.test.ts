import { Hub } from '~/types'
import { closeHub, createHub } from '~/utils/db/hub'

import { deleteKeysWithPrefix } from '../../cdp/_tests/redis'
import { RedisV2, createRedisV2PoolFromConfig } from './redis-v2'

const TEST_KEY_PREFIX = '@posthog/redis-v2-test/v2/'

describe('redis token bucket v2 (single-key)', () => {
    jest.retryTimes(3)

    let hub: Hub
    let redis: RedisV2
    const key = `${TEST_KEY_PREFIX}bucket-1`

    beforeEach(async () => {
        hub = await createHub()
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
        await deleteKeysWithPrefix(redis, TEST_KEY_PREFIX)
    })

    afterEach(async () => {
        await deleteKeysWithPrefix(redis, TEST_KEY_PREFIX)
        await closeHub(hub)
    })

    /**
     * The lua script returns [tokensBefore, tokensAfter]. tokensAfter === -1 signals the
     * cost couldn't be paid; the bucket is left empty (the script does NOT roll back the cost
     * — it stores -1 in `pool` and the next call refills from there).
     */
    const tick = async (
        nowSec: number,
        cost: number,
        poolMax: number,
        fillRate: number,
        expirySec: number,
        targetKey: string = key
    ): Promise<[number, number]> => {
        const result = await redis.useClient({ name: 'test' }, async (client) => {
            return await client.checkRateLimitV2(targetKey, nowSec, cost, poolMax, fillRate, expirySec)
        })
        if (!result) {
            throw new Error('useClient returned null')
        }
        return result
    }

    const readBucket = async (targetKey: string = key): Promise<{ ts: string | null; pool: string | null }> => {
        const result = await redis.useClient({ name: 'read-bucket' }, async (client) => {
            const [ts, pool] = await Promise.all([client.hget(targetKey, 'ts'), client.hget(targetKey, 'pool')])
            return { ts, pool }
        })
        return result ?? { ts: null, pool: null }
    }

    describe('first call (empty bucket)', () => {
        it('returns full pool as tokensBefore and deducts cost', async () => {
            const [before, after] = await tick(1000, 1, 100, 10, 60)
            expect(before).toBe(100)
            expect(after).toBe(99)
        })

        it('persists ts + pool to redis with a positive TTL', async () => {
            await tick(1000, 5, 100, 10, 60)
            const stored = await readBucket()
            expect(stored.ts).toBe('1000')
            expect(stored.pool).toBe('95')

            const ttl = await redis.useClient({ name: 'ttl-check' }, async (client) => client.ttl(key))
            expect(ttl).toBeGreaterThan(0)
        })

        it('returns -1 when first cost exceeds pool size', async () => {
            const [before, after] = await tick(1000, 150, 100, 10, 60)
            expect(before).toBe(100)
            expect(after).toBe(-1)
        })
    })

    describe('cost deduction', () => {
        it('deducts repeated costs from the same bucket', async () => {
            await tick(1000, 30, 100, 10, 60)
            const [before, after] = await tick(1000, 20, 100, 10, 60)
            expect(before).toBe(70)
            expect(after).toBe(50)
        })

        it('returns -1 (and stores -1) when cost exceeds remaining tokens', async () => {
            await tick(1000, 90, 100, 10, 60)
            const [before, after] = await tick(1000, 50, 100, 10, 60)
            expect(before).toBe(10)
            expect(after).toBe(-1)
            expect((await readBucket()).pool).toBe('-1')
        })

        it('treats cost=0 as a peek without changing tokens', async () => {
            await tick(1000, 30, 100, 10, 60)
            const [before, after] = await tick(1000, 0, 100, 10, 60)
            expect(before).toBe(70)
            expect(after).toBe(70)
        })

        it('exposes available tokens via tokensBefore even when rate-limited', async () => {
            await tick(1000, 70, 100, 10, 60) // pool=30
            // Request 50 but only 30 available — call is rate-limited but
            // tokensBefore tells the caller exactly how much they could have spent
            // so they can compute partial allowance (e.g. allow 30/50 = 60%).
            const [before, after] = await tick(1000, 50, 100, 10, 60)
            expect(before).toBe(30)
            expect(after).toBe(-1)
        })
    })

    describe('refill over time', () => {
        it('refills owedTokens = (now - before) * fillRate', async () => {
            await tick(1000, 80, 100, 10, 60) // pool=20
            const [before, after] = await tick(1003, 0, 100, 10, 60)
            // 3 seconds * 10 tokens/sec = 30 owed -> capped not yet hit, 20 + 30 = 50
            expect(before).toBe(50)
            expect(after).toBe(50)
        })

        it('exposes accrued credit in tokensBefore but caps stored pool at poolMax', async () => {
            await tick(1000, 10, 100, 10, 60) // pool=90 stored
            // 5s * 10/s = 50 tokens accrued. tokensBefore reflects the un-capped
            // accrued credit (90 + 50 = 140); tokensAfter is capped at poolMax for
            // storage so silent periods don't let saved credit grow unbounded.
            const [before, after] = await tick(1005, 0, 100, 10, 60)
            expect(before).toBe(140)
            expect(after).toBe(100)
        })

        it('allows a single catch-up call to spend more than poolMax (PR 57920)', async () => {
            await tick(1000, 100, 100, 10, 60) // pool=0
            // 20s of refill at 10/s = 200 accrued credit, double the poolMax.
            // A single catch-up call should be able to redeem all of it.
            const [before, after] = await tick(1020, 199, 100, 10, 60)
            expect(before).toBe(200)
            expect(after).toBe(1)
            expect(after).not.toBe(-1) // not rate-limited
        })

        it('still rate-limits when a catch-up cost exceeds the accrued credit', async () => {
            await tick(1000, 100, 100, 10, 60) // pool=0
            // 5s * 10/s = 50 accrued. Cost of 60 exceeds it.
            const [before, after] = await tick(1005, 60, 100, 10, 60)
            expect(before).toBe(50)
            expect(after).toBe(-1)
        })

        it('lets a previously-exhausted bucket recover after enough time', async () => {
            await tick(1000, 100, 100, 10, 60) // pool=0
            const [before1, after1] = await tick(1000, 1, 100, 10, 60)
            expect(before1).toBe(0)
            expect(after1).toBe(-1)

            // pool stored as -1 right now; +5s = -1 + 50 = 49 capped
            const [before2, after2] = await tick(1005, 10, 100, 10, 60)
            expect(before2).toBe(49)
            expect(after2).toBe(39)
        })
    })

    describe('time going backwards / equal', () => {
        it('treats now == before as zero refill (no negative owedTokens)', async () => {
            await tick(1000, 50, 100, 10, 60)
            const [before, after] = await tick(1000, 10, 100, 10, 60)
            expect(before).toBe(50)
            expect(after).toBe(40)
        })

        it('treats now < before as zero refill and does not advance ts', async () => {
            await tick(2000, 50, 100, 10, 60)
            const [before, after] = await tick(1500, 10, 100, 10, 60)
            // No refill, just deduct
            expect(before).toBe(50)
            expect(after).toBe(40)
            // ts should remain at the later value (2000), not regress to 1500
            expect((await readBucket()).ts).toBe('2000')
        })
    })

    describe('expiry', () => {
        it('refreshes the TTL on every call', async () => {
            await tick(1000, 5, 100, 10, 60)
            await tick(1001, 5, 100, 10, 600)

            const ttl = await redis.useClient({ name: 'ttl-check' }, async (client) => client.ttl(key))
            expect(ttl).toBeGreaterThan(60)
            expect(ttl).toBeLessThanOrEqual(600)
        })
    })

    describe('isolation', () => {
        it('keeps separate buckets for separate keys', async () => {
            const [, afterA] = await tick(1000, 10, 100, 10, 60, `${TEST_KEY_PREFIX}a`)
            const [, afterB] = await tick(1000, 30, 100, 10, 60, `${TEST_KEY_PREFIX}b`)
            expect(afterA).toBe(90)
            expect(afterB).toBe(70)
        })
    })

    describe('pipeline', () => {
        it('returns one [before, after] pair per pipelined call in order', async () => {
            const results = await redis.usePipeline({ name: 'pipeline-test' }, (pipeline) => {
                pipeline.checkRateLimitV2(key, 1000, 10, 100, 10, 60)
                pipeline.checkRateLimitV2(key, 1000, 30, 100, 10, 60)
                pipeline.checkRateLimitV2(key, 1000, 5, 100, 10, 60)
            })

            expect(results).not.toBeNull()
            const tuples = results!.map(([err, val]) => {
                expect(err).toBeNull()
                return val as [number, number]
            })
            expect(tuples).toEqual([
                [100, 90],
                [90, 60],
                [60, 55],
            ])
        })

        it('threads state through the rate-limit boundary in a single pipeline', async () => {
            const results = await redis.usePipeline({ name: 'pipeline-rate-limit' }, (pipeline) => {
                pipeline.checkRateLimitV2(key, 1000, 90, 100, 10, 60) // 100 -> 10
                pipeline.checkRateLimitV2(key, 1000, 9, 100, 10, 60) //  10 -> 1
                pipeline.checkRateLimitV2(key, 1000, 2, 100, 10, 60) //   1 -> -1 (rate-limited)
                pipeline.checkRateLimitV2(key, 1000, 1, 100, 10, 60) //  -1 -> -1 (still rate-limited)
            })

            expect(results).not.toBeNull()
            const tuples = results!.map(([err, val]) => {
                expect(err).toBeNull()
                return val as [number, number]
            })
            expect(tuples).toEqual([
                [100, 10],
                [10, 1],
                [1, -1],
                [-1, -1],
            ])
        })
    })

    describe('concurrent calls', () => {
        it('serializes concurrent calls so total deducted equals sum of costs (atomicity)', async () => {
            const promises = Array.from({ length: 20 }, () => tick(1000, 1, 100, 10, 60))
            const results = await Promise.all(promises)
            const finalAfter = Math.min(...results.map(([, a]) => a))
            // All 20 succeed since 100 - 20 >= 0
            expect(results.every(([, a]) => a !== -1)).toBe(true)
            expect(finalAfter).toBe(80)
            expect((await readBucket()).pool).toBe('80')
        })
    })
})
