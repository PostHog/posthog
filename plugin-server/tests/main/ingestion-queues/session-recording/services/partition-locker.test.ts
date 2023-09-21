import { TopicPartition } from 'kafkajs'

import {
    PartitionLocker,
    topicPartitionKey,
} from '../../../../../src/main/ingestion-queues/session-recording/services/partition-locker'
import { Hub } from '../../../../../src/types'
import { createHub } from '../../../../../src/utils/db/hub'
import { delay } from '../../../../../src/utils/utils'

describe('PartitionLocker', () => {
    jest.setTimeout(1000)
    let hub: Hub
    let closeHub: () => Promise<void>
    const keyPrefix = 'test-partition-locker'
    let partitionLocker: PartitionLocker
    let otherPartitionLocker: PartitionLocker

    const tp = (partition: number, topic = 'topic') => ({ topic, partition })

    async function deletePrefixedKeys() {
        const redisClient = await hub.redisPool.acquire()
        const keys = await redisClient.keys(`${keyPrefix}*`)
        const pipeline = redisClient.pipeline()
        keys.forEach(function (key) {
            pipeline.del(key)
        })
        await pipeline.exec()
        await hub.redisPool.release(redisClient)
    }

    async function getValuesFromRedis(tp: TopicPartition) {
        const client = await hub.redisPool.acquire()
        const key = topicPartitionKey(keyPrefix, tp)
        const redisValue = await client.get(key)
        await hub.redisPool.release(client)

        return redisValue
    }

    beforeEach(async () => {
        ;[hub, closeHub] = await createHub()

        otherPartitionLocker = new PartitionLocker(hub.redisPool, keyPrefix)
        otherPartitionLocker.delay = 50
        otherPartitionLocker.ttl = 500

        partitionLocker = new PartitionLocker(hub.redisPool, keyPrefix)
        partitionLocker.delay = 50
        partitionLocker.ttl = 500
    })

    afterEach(async () => {
        await deletePrefixedKeys()
        await closeHub()
    })

    describe('with no existing claims', () => {
        it('can claim a range of partitions', async () => {
            expect(await getValuesFromRedis(tp(1))).toBe(null)
            expect(await getValuesFromRedis(tp(2))).toBe(null)
            const cb = jest.fn()
            void partitionLocker.claim([tp(1), tp(2)]).then(cb)

            await delay(100)

            expect(cb).toHaveBeenCalled()
            expect(await getValuesFromRedis(tp(1))).toBe(partitionLocker.consumerID)
            expect(await getValuesFromRedis(tp(2))).toBe(partitionLocker.consumerID)
        })

        it('waits for a claim to ttl', async () => {
            await otherPartitionLocker.claim([tp(1)])
            expect(await getValuesFromRedis(tp(1))).toBe(otherPartitionLocker.consumerID)
            expect(await getValuesFromRedis(tp(2))).toBe(null)

            const cb = jest.fn()
            void partitionLocker.claim([tp(1), tp(2)]).then(cb)

            await delay(100)
            expect(cb).not.toHaveBeenCalled()
            expect(await getValuesFromRedis(tp(1))).toBe(otherPartitionLocker.consumerID)
            expect(await getValuesFromRedis(tp(2))).toBe(partitionLocker.consumerID)
            // Over the ttl
            await delay(500)
            expect(cb).toHaveBeenCalled()
            expect(await getValuesFromRedis(tp(1))).toBe(partitionLocker.consumerID)
            expect(await getValuesFromRedis(tp(2))).toBe(partitionLocker.consumerID)
        })

        it('releases a claim if owned', async () => {
            await otherPartitionLocker.claim([tp(1)])
            expect(await getValuesFromRedis(tp(1))).toBe(otherPartitionLocker.consumerID)
            await partitionLocker.release([tp(1)])
            expect(await getValuesFromRedis(tp(1))).toBe(otherPartitionLocker.consumerID)
            await otherPartitionLocker.release([tp(1)])
            expect(await getValuesFromRedis(tp(1))).toBe(null)
        })
    })
})
