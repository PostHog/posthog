import { mkdirSync, rmSync } from 'node:fs'
import path from 'path'

import { waitForExpect } from '../../../../functional_tests/expectations'
import { defaultConfig } from '../../../../src/config/config'
import { SessionRecordingBlobIngester } from '../../../../src/main/ingestion-queues/session-recording/session-recordings-blob-consumer'
import { Hub, PluginsServerConfig } from '../../../../src/types'
import { createHub } from '../../../../src/utils/db/hub'
import { createIncomingRecordingMessage } from './fixtures'

const keyPrefix = 'test-session-offset-high-water-mark'

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

jest.mock('../../../../src/kafka/batch-consumer', () => {
    return {
        startBatchConsumer: jest.fn(() =>
            Promise.resolve({
                join: () => ({
                    finally: jest.fn(),
                }),
                stop: jest.fn(),
                consumer: {
                    on: jest.fn(),
                    commitSync: jest.fn(),
                },
            })
        ),
    }
})

const veryShortFlushInterval = 5
describe('ingester', () => {
    const config: PluginsServerConfig = {
        ...defaultConfig,
        SESSION_RECORDING_LOCAL_DIRECTORY: '.tmp/test-session-recordings',
    }

    let ingester: SessionRecordingBlobIngester

    let hub: Hub
    let closeHub: () => Promise<void>

    beforeAll(() => {
        mkdirSync(path.join(config.SESSION_RECORDING_LOCAL_DIRECTORY, 'session-buffer-files'), { recursive: true })
    })

    beforeEach(async () => {
        ;[hub, closeHub] = await createHub()
    })

    afterEach(async () => {
        await ingester.stop()
        await deleteKeysWithPrefix(hub, keyPrefix)
        await closeHub()
    })

    afterAll(() => {
        rmSync(config.SESSION_RECORDING_LOCAL_DIRECTORY, { recursive: true, force: true })
    })

    // these tests assume that a flush won't run while they run
    describe('with long flush interval', () => {
        beforeEach(async () => {
            ingester = new SessionRecordingBlobIngester(
                hub.teamManager,
                {
                    ...defaultConfig,
                    SESSION_RECORDING_REDIS_OFFSET_STORAGE_KEY: keyPrefix,
                },
                hub.objectStorage,
                hub.redisPool,
                veryShortFlushInterval * 100_000
            )
            await ingester.start()
        })

        it('creates a new session manager if needed', async () => {
            const event = createIncomingRecordingMessage()
            await ingester.consume(event)
            await waitForExpect(() => {
                expect(ingester.sessions.size).toBe(1)
                expect(ingester.sessions.has('1-session_id_1')).toEqual(true)
            })
        })

        it('removes sessions on destroy', async () => {
            await ingester.consume(createIncomingRecordingMessage({ team_id: 2, session_id: 'session_id_1' }))
            await ingester.consume(createIncomingRecordingMessage({ team_id: 2, session_id: 'session_id_2' }))

            expect(ingester.sessions.size).toBe(2)
            expect(ingester.sessions.has('2-session_id_1')).toEqual(true)
            expect(ingester.sessions.has('2-session_id_2')).toEqual(true)

            await ingester.destroySessions([['2-session_id_1', ingester.sessions.get('2-session_id_1')!]])

            expect(ingester.sessions.size).toBe(1)
            expect(ingester.sessions.has('2-session_id_2')).toEqual(true)
        })

        it('handles multiple incoming sessions', async () => {
            const event = createIncomingRecordingMessage()
            const event2 = createIncomingRecordingMessage({
                session_id: 'session_id_2',
            })
            await Promise.all([ingester.consume(event), ingester.consume(event2)])
            expect(ingester.sessions.size).toBe(2)
            expect(ingester.sessions.has('1-session_id_1')).toEqual(true)
            expect(ingester.sessions.has('1-session_id_2')).toEqual(true)
        })
    })

    describe('with short flush interval', () => {
        beforeEach(async () => {
            ingester = new SessionRecordingBlobIngester(
                hub.teamManager,
                defaultConfig,
                hub.objectStorage,
                hub.redisPool,
                veryShortFlushInterval
            )
            await ingester.start()
        })

        it('destroys a session manager if finished', async () => {
            const event = createIncomingRecordingMessage()
            await ingester.consume(event)
            expect(ingester.sessions.has('1-session_id_1')).toEqual(true)
            await ingester.sessions.get('1-session_id_1')?.flush('buffer_age')

            await new Promise((resolve) => setTimeout(resolve, veryShortFlushInterval))

            expect(ingester.sessions.has('1-session_id_1')).toEqual(false)
        })
    })

    // it('skips messages that are below the high-water mark', async () => {
    //     mockHighWaterMark.get.mockResolvedValue(1000)
    //
    //     await sessionManager.add(
    //         createIncomingRecordingMessage({
    //             metadata: {
    //                 offset: 998,
    //             } as any,
    //         })
    //     )
    //     expect(sessionManager.buffer.count).toEqual(0)
    //     expect(sessionManager.buffer.offsets).toEqual([998])
    //
    //     await sessionManager.add(
    //         createIncomingRecordingMessage({
    //             metadata: {
    //                 offset: 1000,
    //             } as any,
    //         })
    //     )
    //     expect(sessionManager.buffer.count).toEqual(0)
    //     expect(sessionManager.buffer.offsets).toEqual([998, 1000])
    //
    //     await sessionManager.add(
    //         createIncomingRecordingMessage({
    //             metadata: {
    //                 offset: 1001,
    //             } as any,
    //         })
    //     )
    //     expect(sessionManager.buffer.count).toEqual(1)
    //     expect(sessionManager.buffer.offsets).toEqual([998, 1000, 1001])
    // })
})
