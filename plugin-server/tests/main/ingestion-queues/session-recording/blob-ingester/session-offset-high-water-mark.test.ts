import { SessionOffsetHighWaterMark } from '../../../../../src/main/ingestion-queues/session-recording/blob-ingester/session-offset-high-water-mark'
import { Hub } from '../../../../../src/types'
import { createHub } from '../../../../../src/utils/db/hub'

async function deleteKeysWithPrefix(hub: Hub, keyPrefix: string) {
    const redisClient = await hub.redisPool.acquire()
    const keys = await redisClient.keys(`${keyPrefix}*`)
    const pipeline = redisClient.pipeline()
    keys.forEach(function (key) {
        console.log('deleting key', key)
        pipeline.del(key)
    })
    await pipeline.exec()
    await hub.redisPool.release(redisClient)
}

describe('session offset high-water mark', () => {
    let hub: Hub
    let closeHub: () => Promise<void>
    const keyPrefix = 'test-high-water-mark'
    let sessionOffsetHighWaterMark: SessionOffsetHighWaterMark

    beforeEach(async () => {
        ;[hub, closeHub] = await createHub()
        sessionOffsetHighWaterMark = new SessionOffsetHighWaterMark(hub.redisPool, keyPrefix)
        // works even before anything is written to redis
        expect(await sessionOffsetHighWaterMark.getAll({ topic: 'topic', partition: 1 })).toStrictEqual({})

        await sessionOffsetHighWaterMark.add({ topic: 'topic', partition: 1 }, 'some-session', 123)
        await sessionOffsetHighWaterMark.add({ topic: 'topic', partition: 1 }, 'another-session', 12)
        await sessionOffsetHighWaterMark.add({ topic: 'topic', partition: 2 }, 'a-third-session', 1)
    })

    afterEach(async () => {
        await deleteKeysWithPrefix(hub, keyPrefix)
        await closeHub()
    })

    it('can get high-water marks for all sessions for a partition', async () => {
        expect(await sessionOffsetHighWaterMark.getAll({ topic: 'topic', partition: 1 })).toEqual({
            'some-session': 123,
            'another-session': 12,
        })
    })

    it('can remove all high-water marks based on a given offset', async () => {
        await sessionOffsetHighWaterMark.onCommit({ topic: 'topic', partition: 1 }, 12)

        // removes all high-water marks that are <= 12
        expect(await sessionOffsetHighWaterMark.getAll({ topic: 'topic', partition: 1 })).toEqual({
            'some-session': 123,
        })
        // does not affect other partitions
        expect(await sessionOffsetHighWaterMark.getAll({ topic: 'topic', partition: 2 })).toEqual({
            'a-third-session': 1,
        })
    })

    it('can check if an offset is below the high-water mark', async () => {
        const partitionOneTestCases: [number, boolean][] = [
            [124, false],
            [123, true],
            [12, true],
            [11, true],
            [1, true],
            [0, true],
        ]
        await Promise.allSettled(
            partitionOneTestCases.map(async ([offset, expected]) => {
                expect(
                    await sessionOffsetHighWaterMark.isBelowHighWaterMark(
                        { topic: 'topic', partition: 1 },
                        'some-session',
                        offset
                    )
                ).toBe(expected)
            })
        )
    })

    it('can check if an offset is below the high-water mark even if we have never seen it before', async () => {
        // there is nothing for a partition? we are always below the high-water mark
        expect(
            await sessionOffsetHighWaterMark.isBelowHighWaterMark(
                { topic: 'topic', partition: 1 },
                'anything we did not add yet',
                5432
            )
        ).toBe(false)
    })
})
