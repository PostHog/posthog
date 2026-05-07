import { Hub } from '~/types'
import { closeHub, createHub } from '~/utils/db/hub'

import { deleteKeysWithPrefix } from '../../cdp/_tests/redis'
import { RateLimitBucket, checkRateLimitV3Many } from './redis-token-bucket-v3.lua'
import { RedisV2, createRedisV2PoolFromConfig } from './redis-v2'

const TEST_KEY_PREFIX = '@posthog/redis-v3-test/'

describe('redis token bucket v3 multi-key', () => {
    jest.retryTimes(3)

    let hub: Hub
    let redis: RedisV2
    const k = (name: string) => `${TEST_KEY_PREFIX}${name}`

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

    const bucket = (
        key: string,
        now: number,
        cost: number,
        poolMax: number = 100,
        fillRate: number = 10,
        expiry: number = 60
    ): RateLimitBucket => ({ key, now, cost, poolMax, fillRate, expiry })

    const runMulti = async (buckets: RateLimitBucket[]): Promise<Array<[number, number]>> => {
        const result = await redis.useClient({ name: 'v3-many-test' }, async (client) =>
            checkRateLimitV3Many(client, buckets, 'test')
        )
        if (!result) {
            throw new Error('useClient returned null')
        }
        return result
    }

    const readBucket = async (target: string): Promise<{ ts: string | null; pool: string | null }> => {
        const result = await redis.useClient({ name: 'read-bucket' }, async (client) => {
            const [ts, pool] = await Promise.all([client.hget(target, 'ts'), client.hget(target, 'pool')])
            return { ts, pool }
        })
        return result ?? { ts: null, pool: null }
    }

    it('returns an empty array for an empty input (short-circuit, no script call)', async () => {
        const tuples = await runMulti([])
        expect(tuples).toEqual([])
    })

    it('processes multiple independent buckets in one call', async () => {
        const tuples = await runMulti([bucket(k('a'), 1000, 10), bucket(k('b'), 1000, 30), bucket(k('c'), 1000, 5)])
        expect(tuples).toEqual([
            [100, 90],
            [100, 70],
            [100, 95],
        ])
    })

    it('threads state across repeated keys within the same call (sequential, not parallel)', async () => {
        // Same key three times — each invocation sees the previous bucket's
        // state, so we walk 100 -> 90 -> 60 -> 55 just like a pipeline would.
        const key = k('repeated')
        const tuples = await runMulti([bucket(key, 1000, 10), bucket(key, 1000, 30), bucket(key, 1000, 5)])
        expect(tuples).toEqual([
            [100, 90],
            [90, 60],
            [60, 55],
        ])
    })

    it('persists each bucket independently', async () => {
        await runMulti([bucket(k('a'), 1000, 10), bucket(k('b'), 1000, 30)])
        const a = await readBucket(k('a'))
        const b = await readBucket(k('b'))
        expect(a).toEqual({ ts: '1000', pool: '90' })
        expect(b).toEqual({ ts: '1000', pool: '70' })
    })

    it('matches V2 single-key behaviour for the same call (cross-version equivalence)', async () => {
        // V2 reference run on an isolated key
        const v2Key = `${TEST_KEY_PREFIX}cross/v2`
        const v2Result = await redis.useClient({ name: 'v2-cross' }, async (client) =>
            client.checkRateLimitV2(v2Key, 1000, 30, 100, 10, 60)
        )
        const [v3Result] = await runMulti([bucket(`${TEST_KEY_PREFIX}cross/v3`, 1000, 30)])
        expect(v3Result).toEqual(v2Result)
    })

    it('exposes uncapped accrued credit (PR 57920 fix)', async () => {
        await runMulti([bucket(k('a'), 1000, 100)]) // pool=0
        const [tuple] = await runMulti([bucket(k('a'), 1020, 199)])
        expect(tuple).toEqual([200, 1])
    })

    it('sets TTL to 2x expiry on creation', async () => {
        await runMulti([bucket(k('ttl'), 1000, 5, 100, 10, 60)])
        const ttl = await redis.useClient({ name: 'ttl-check' }, async (client) => await client.ttl(k('ttl')))
        expect(ttl).toBeGreaterThan(60)
        expect(ttl).toBeLessThanOrEqual(120)
    })

    it('does NOT refresh TTL while remaining is above expiry/2', async () => {
        await runMulti([bucket(k('ttl-stable'), 1000, 1, 100, 10, 60)])
        await redis.useClient({ name: 'pexpire' }, async (client) => await client.pexpire(k('ttl-stable'), 50_000))
        await runMulti([bucket(k('ttl-stable'), 1001, 1, 100, 10, 60)])
        const ttl = await redis.useClient({ name: 'pttl-check' }, async (client) => await client.pttl(k('ttl-stable')))
        expect(ttl).toBeGreaterThan(0)
        expect(ttl).toBeLessThanOrEqual(50_000)
    })

    it('refreshes TTL once remaining drops below expiry/2', async () => {
        await runMulti([bucket(k('ttl-refresh'), 1000, 1, 100, 10, 60)])
        await redis.useClient({ name: 'pexpire' }, async (client) => await client.pexpire(k('ttl-refresh'), 10_000))
        await runMulti([bucket(k('ttl-refresh'), 1001, 1, 100, 10, 60)])
        const ttl = await redis.useClient({ name: 'pttl-check' }, async (client) => await client.pttl(k('ttl-refresh')))
        expect(ttl).toBeGreaterThan(60_000)
        expect(ttl).toBeLessThanOrEqual(120_000)
    })
})
