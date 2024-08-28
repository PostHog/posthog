import { Redis } from 'ioredis'

import { OverflowManager } from '../../../../../src/main/ingestion-queues/session-recording/services/overflow-manager'
import { Hub } from '../../../../../src/types'
import { closeHub, createHub } from '../../../../../src/utils/db/hub'

jest.mock('../../../../../src/utils/status')
jest.mock('../../../../../src/kafka/producer')

const CAPTURE_OVERFLOW_REDIS_KEY = '@posthog/capture-overflow/replay'

describe('overflow manager', () => {
    let hub: Hub
    let redis: Redis
    let overflowManager: OverflowManager

    beforeAll(async () => {
        hub = await createHub()
        redis = await hub.redisPool.acquire()
    })
    beforeEach(async () => {
        await redis.del(CAPTURE_OVERFLOW_REDIS_KEY)
        overflowManager = new OverflowManager(100, 10, 20, 3600, CAPTURE_OVERFLOW_REDIS_KEY, redis)
    })

    afterAll(async () => {
        await redis.flushdb()
        await hub.redisPool.release(redis)
        await closeHub?.()
    })

    test('it does not trigger if several keys are under threshold', async () => {
        await overflowManager.observe('key1', 80)
        await overflowManager.observe('key2', 80)
        await overflowManager.observe('key3', 80)

        expect(await redis.exists(CAPTURE_OVERFLOW_REDIS_KEY)).toEqual(0)
    })

    test('it triggers on size count', async () => {
        await overflowManager.observe('key1', 40)
        await overflowManager.observe('key1', 40)
        await overflowManager.observe('key2', 80)
        expect(await redis.exists(CAPTURE_OVERFLOW_REDIS_KEY)).toEqual(0)

        await overflowManager.observe('key1', 40)
        expect(await redis.zrange(CAPTURE_OVERFLOW_REDIS_KEY, 0, -1)).toEqual(['key1'])
    })

    test('it triggers for many small calls', async () => {
        await overflowManager.observe('key1', 1) // Will consume 20 due to minPerCall, penalize poorly batched traffic
        await overflowManager.observe('key1', 1)
        await overflowManager.observe('key1', 1)
        await overflowManager.observe('key1', 1)
        await overflowManager.observe('key2', 80)
        expect(await redis.exists(CAPTURE_OVERFLOW_REDIS_KEY)).toEqual(0)

        await overflowManager.observe('key1', 31)
        expect(await redis.zrange(CAPTURE_OVERFLOW_REDIS_KEY, 0, -1)).toEqual(['key1'])
    })

    test('it does not triggers twice when cooling down', async () => {
        await overflowManager.observe('key1', 110)
        expect(await redis.zrange(CAPTURE_OVERFLOW_REDIS_KEY, 0, -1)).toEqual(['key1'])

        // Delete the key to confirm that OverflowManager is in cooldown for key1 and does not re-create it
        await redis.del(CAPTURE_OVERFLOW_REDIS_KEY)
        await overflowManager.observe('key1', 110)
        expect(await redis.exists(CAPTURE_OVERFLOW_REDIS_KEY)).toEqual(0)

        // But it triggers for key2
        await overflowManager.observe('key2', 110)
        expect(await redis.zrange(CAPTURE_OVERFLOW_REDIS_KEY, 0, -1)).toEqual(['key2'])
    })

    test('it does not update existing values', async () => {
        const timestamp = 1711280335000
        const oldTimestamp = timestamp / 1000 - 200
        await redis.zadd(CAPTURE_OVERFLOW_REDIS_KEY, oldTimestamp, 'key1')

        await overflowManager.observe('key1', 110, timestamp)
        expect(await redis.zrange(CAPTURE_OVERFLOW_REDIS_KEY, 0, -1, 'WITHSCORES')).toEqual([
            'key1',
            oldTimestamp.toString(),
        ])
    })

    test('it set the expected expiration on new values', async () => {
        const timestamp = 1711280335000
        const oldTimestamp = timestamp / 1000 - 200
        await redis.zadd(CAPTURE_OVERFLOW_REDIS_KEY, oldTimestamp, 'key1')

        const expectedExpiration = timestamp / 1000 + 3600
        await overflowManager.observe('key2', 110, timestamp)
        expect(await redis.zrange(CAPTURE_OVERFLOW_REDIS_KEY, 0, -1, 'WITHSCORES')).toEqual([
            'key1',
            oldTimestamp.toString(),
            'key2',
            expectedExpiration.toString(),
        ])
    })

    test('it removes old values when adding one', async () => {
        const timestamp = 1711280335000
        const oldTimestamp = timestamp / 1000 - 8000
        await redis.zadd(CAPTURE_OVERFLOW_REDIS_KEY, oldTimestamp, 'key1')

        const expectedExpiration = timestamp / 1000 + 3600
        await overflowManager.observe('key2', 110, timestamp)
        expect(await redis.zrange(CAPTURE_OVERFLOW_REDIS_KEY, 0, -1, 'WITHSCORES')).toEqual([
            'key2',
            expectedExpiration.toString(),
        ])
    })
})
