import { Redis } from 'ioredis'

import { OverflowManager } from '../../../../../src/main/ingestion-queues/session-recording/services/overflow-manager'
import { Hub } from '../../../../../src/types'
import { createHub } from '../../../../../src/utils/db/hub'

jest.mock('../../../../../src/utils/status')
jest.mock('../../../../../src/kafka/producer')

const CAPTURE_OVERFLOW_REDIS_KEY = '@posthog/capture-overflow/replay'
const TIMESTAMP_IN_2017 = 1511220335

describe('overflow manager', () => {
    let hub: Hub
    let closeHub: () => Promise<void>
    let redis: Redis
    let overflowManager: OverflowManager

    beforeAll(async () => {
        ;[hub, closeHub] = await createHub()
        redis = await hub.redisPool.acquire()
    })
    beforeEach(async () => {
        await redis.del(CAPTURE_OVERFLOW_REDIS_KEY)
        overflowManager = new OverflowManager(10, 1, 3600, CAPTURE_OVERFLOW_REDIS_KEY, redis)
    })

    afterAll(async () => {
        await redis.flushdb()
        await hub.redisPool.release(redis)
        await closeHub?.()
    })

    test('it does not trigger if several keys are under threshold', async () => {
        await overflowManager.observe('key1', 8)
        await overflowManager.observe('key2', 8)
        await overflowManager.observe('key3', 8)

        expect(await redis.exists(CAPTURE_OVERFLOW_REDIS_KEY)).toEqual(0)
    })

    test('it triggers for hot keys', async () => {
        await overflowManager.observe('key1', 4)
        await overflowManager.observe('key1', 4)
        await overflowManager.observe('key2', 8)
        expect(await redis.exists(CAPTURE_OVERFLOW_REDIS_KEY)).toEqual(0)

        await overflowManager.observe('key1', 4)
        expect(await redis.zrange(CAPTURE_OVERFLOW_REDIS_KEY, 0, -1)).toEqual(['key1'])
    })

    test('it does not triggers twice when cooling down', async () => {
        await overflowManager.observe('key1', 11)
        expect(await redis.zrange(CAPTURE_OVERFLOW_REDIS_KEY, 0, -1)).toEqual(['key1'])

        // Delete the key to confirm that OverflowManager is in cooldown for key1 and does not re-create it
        await redis.del(CAPTURE_OVERFLOW_REDIS_KEY)
        await overflowManager.observe('key1', 11)
        expect(await redis.exists(CAPTURE_OVERFLOW_REDIS_KEY)).toEqual(0)

        // But it triggers for key2
        await overflowManager.observe('key2', 11)
        expect(await redis.zrange(CAPTURE_OVERFLOW_REDIS_KEY, 0, -1)).toEqual(['key2'])
    })

    test('it does not update existing values', async () => {
        await redis.zadd(CAPTURE_OVERFLOW_REDIS_KEY, TIMESTAMP_IN_2017, 'key1')

        await overflowManager.observe('key1', 11)
        expect(await redis.zrange(CAPTURE_OVERFLOW_REDIS_KEY, 0, -1, 'WITHSCORES')).toEqual([
            'key1',
            TIMESTAMP_IN_2017.toString(),
        ])
    })

    test('it set the expected expiration on new values', async () => {
        await redis.zadd(CAPTURE_OVERFLOW_REDIS_KEY, TIMESTAMP_IN_2017, 'key1')

        const timestamp = 1711280335000
        const expectedExpiration = timestamp / 1000 + 3600
        await overflowManager.observe('key2', 11, timestamp)
        expect(await redis.zrange(CAPTURE_OVERFLOW_REDIS_KEY, 0, -1, 'WITHSCORES')).toEqual([
            'key1',
            TIMESTAMP_IN_2017.toString(),
            'key2',
            expectedExpiration.toString(),
        ])
    })
})
