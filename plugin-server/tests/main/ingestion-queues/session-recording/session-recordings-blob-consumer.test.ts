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

const mockCommit = jest.fn()

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
                    commit: mockCommit,
                },
            })
        ),
    }
})

jest.setTimeout(1000)

describe('ingester', () => {
    const config: PluginsServerConfig = {
        ...defaultConfig,
        SESSION_RECORDING_LOCAL_DIRECTORY: '.tmp/test-session-recordings',
    }

    let ingester: SessionRecordingBlobIngester

    let hub: Hub
    let closeHub: () => Promise<void>

    beforeAll(() => {
        jest.useFakeTimers({
            // magic is for evil wizards
            // setInterval in blob consumer doesn't fire
            // if legacyFakeTimers is false
            // 🤷
            legacyFakeTimers: true,
        })
        mkdirSync(path.join(config.SESSION_RECORDING_LOCAL_DIRECTORY, 'session-buffer-files'), { recursive: true })
    })

    beforeEach(async () => {
        ;[hub, closeHub] = await createHub()
    })

    afterEach(async () => {
        jest.runOnlyPendingTimers()
        await deleteKeysWithPrefix(hub, keyPrefix)
        await ingester.stop()
        await closeHub()
    })

    afterAll(() => {
        rmSync(config.SESSION_RECORDING_LOCAL_DIRECTORY, { recursive: true, force: true })
        jest.useRealTimers()
    })

    // these tests assume that a flush won't run while they run
    beforeEach(async () => {
        ingester = new SessionRecordingBlobIngester(
            hub.teamManager,
            {
                ...defaultConfig,
                SESSION_RECORDING_REDIS_OFFSET_STORAGE_KEY: keyPrefix,
            },
            hub.objectStorage,
            hub.redisPool
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

    it('destroys a session manager if finished', async () => {
        const event = createIncomingRecordingMessage()
        await ingester.consume(event)
        expect(ingester.sessions.has('1-session_id_1')).toEqual(true)
        await ingester.sessions.get('1-session_id_1')?.flush('buffer_age')

        jest.runOnlyPendingTimers() // flush timer

        expect(ingester.sessions.has('1-session_id_1')).toEqual(false)
    })

    describe('offset committing', () => {
        const metadata = {
            partition: 1,
            topic: 'session_recording_events',
        }
        let _offset = 1
        const offset = () => _offset++

        const addMessage = (session_id: string) =>
            createIncomingRecordingMessage({ session_id }, { ...metadata, offset: offset() })

        beforeEach(() => {
            _offset = 1
        })

        it('should commit offsets in simple cases', async () => {
            await ingester.consume(addMessage('sid1'))
            await ingester.consume(addMessage('sid1'))
            await ingester.sessions.get('1-sid1')?.flush('buffer_age')

            expect(mockCommit).toHaveBeenCalledTimes(1)
            expect(mockCommit).toHaveBeenCalledWith({
                ...metadata,
                offset: 3,
            })
        })

        it('should commit the lowest known offset if there is a blocking session', async () => {
            await ingester.consume(addMessage('sid1')) // 1
            await ingester.consume(addMessage('sid2')) // 2
            await ingester.consume(addMessage('sid2')) // 3
            await ingester.consume(addMessage('sid2')) // 4
            await ingester.sessions.get('1-sid2')?.flush('buffer_age')

            // No offsets are below the blocking one
            expect(mockCommit).not.toHaveBeenCalled()
            await ingester.sessions.get('1-sid1')?.flush('buffer_age')
            // We can only commit up to 2 because we don't track the other removed offsets - no biggy as this is super edge casey
            expect(mockCommit).toHaveBeenLastCalledWith({
                ...metadata,
                offset: 2,
            })
        })

        it('should commit one lower than the blocking session if that is the highest', async () => {
            await ingester.consume(addMessage('sid1')) // 1
            await ingester.consume(addMessage('sid2')) // 2
            await ingester.consume(addMessage('sid2')) // 3
            await ingester.consume(addMessage('sid2')) // 4
            await ingester.sessions.get('1-sid2')?.flush('buffer_age')

            // No offsets are below the blocking one
            expect(mockCommit).not.toHaveBeenCalled()
            await ingester.consume(addMessage('sid2')) // 5
            await ingester.sessions.get('1-sid1')?.flush('buffer_age')

            expect(mockCommit).toHaveBeenLastCalledWith({
                ...metadata,
                offset: 5, // Same as the blocking session and more than the highest commitable for sid1 (1)
            })
        })

        it('should not be affected by other partitions ', async () => {
            createIncomingRecordingMessage({ session_id: 'sid1' }, { ...metadata, partition: 2, offset: offset() })
            await ingester.consume(addMessage('sid2')) // 2
            await ingester.consume(addMessage('sid2')) // 3

            await ingester.sessions.get('1-sid2')?.flush('buffer_age')

            expect(mockCommit).toHaveBeenLastCalledWith({
                ...metadata,
                offset: 4,
            })
        })
    })
})
