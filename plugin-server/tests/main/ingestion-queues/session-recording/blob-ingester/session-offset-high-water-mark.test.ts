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

    beforeEach(async () => {
        ;[hub, closeHub] = await createHub()
    })

    afterEach(async () => {
        await deleteKeysWithPrefix(hub, keyPrefix)
        await closeHub()
    })

    it('works even if there is nothing in redis', async () => {
        const thing = new SessionOffsetHighWaterMark(hub.redisPool, keyPrefix)
        expect(await thing.getAll('topic', 1)).toStrictEqual({})
    })

    it('can get high-water marks for all sessions for a partition', async () => {
        const thing = new SessionOffsetHighWaterMark(hub.redisPool, keyPrefix)

        await thing.add('topic', 1, 'some-session', 123)
        await thing.add('topic', 1, 'another-session', 12)
        await thing.add('topic', 2, 'a-third-session', 1)

        expect(await thing.getAll('topic', 1)).toEqual({
            'some-session': 123,
            'another-session': 12,
        })
    })

    it('can remove all high-water marks based on a given offset', async () => {
        const thing = new SessionOffsetHighWaterMark(hub.redisPool, keyPrefix)

        await thing.add('topic', 1, 'expected-to-stay-session', 124)
        await thing.add('topic', 1, 'some-session', 123)
        await thing.add('topic', 1, 'another-session', 12)
        await thing.add('topic', 2, 'a-third-session', 1)

        await thing.onCommit('topic', 1, 123)

        expect(await thing.getAll('topic', 1)).toEqual({
            'expected-to-stay-session': 124,
        })
        expect(await thing.getAll('topic', 2)).toEqual({
            'a-third-session': 1,
        })
    })

    it('can check if an offset is below the high-water mark', async () => {
        const thing = new SessionOffsetHighWaterMark(hub.redisPool, keyPrefix)

        await thing.add('topic', 1, 'some-session', 123)
        await thing.add('topic', 1, 'another-session', 12)
        await thing.add('topic', 2, 'a-third-session', 1)

        expect(await thing.isBelowHighWaterMark('topic', 1, 'some-session', 124)).toBe(false)
        expect(await thing.isBelowHighWaterMark('topic', 1, 'some-session', 123)).toBe(true)
        expect(await thing.isBelowHighWaterMark('topic', 1, 'some-session', 12)).toBe(true)
        expect(await thing.isBelowHighWaterMark('topic', 1, 'some-session', 11)).toBe(true)

        expect(await thing.isBelowHighWaterMark('topic', 1, 'another-session', 124)).toBe(false)
        expect(await thing.isBelowHighWaterMark('topic', 1, 'another-session', 123)).toBe(false)
        expect(await thing.isBelowHighWaterMark('topic', 1, 'another-session', 12)).toBe(true)
        expect(await thing.isBelowHighWaterMark('topic', 1, 'another-session', 11)).toBe(true)

        expect(await thing.isBelowHighWaterMark('topic', 2, 'a-third-session', 124)).toBe(false)
        expect(await thing.isBelowHighWaterMark('topic', 2, 'a-third-session', 123)).toBe(false)
        expect(await thing.isBelowHighWaterMark('topic', 2, 'a-third-session', 12)).toBe(false)
        expect(await thing.isBelowHighWaterMark('topic', 2, 'a-third-session', 11)).toBe(false)
        expect(await thing.isBelowHighWaterMark('topic', 2, 'a-third-session', 1)).toBe(true)
        expect(await thing.isBelowHighWaterMark('topic', 2, 'a-third-session', 0)).toBe(true)

        // there is nothing for a partition? we are always below the high-water mark
        expect(await thing.isBelowHighWaterMark('topic', 1, 'anything we did not add yet', 5432)).toBe(false)
    })
})
