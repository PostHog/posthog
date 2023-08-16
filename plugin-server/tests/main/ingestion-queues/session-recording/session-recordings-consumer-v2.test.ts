import { mkdirSync, rmSync } from 'node:fs'
import path from 'path'

import { waitForExpect } from '../../../../functional_tests/expectations'
import { defaultConfig } from '../../../../src/config/config'
import { SessionRecordingIngesterV2 } from '../../../../src/main/ingestion-queues/session-recording/session-recordings-consumer-v2'
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
                    commitSync: mockCommit,
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

    let ingester: SessionRecordingIngesterV2

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
        ingester = new SessionRecordingIngesterV2(
            {
                ...defaultConfig,
                SESSION_RECORDING_REDIS_OFFSET_STORAGE_KEY: keyPrefix,
            },
            hub.postgres,
            hub.objectStorage,
            hub.redisPool
        )
        await ingester.start()
    })

    it('creates a new session manager if needed', async () => {
        const event = createIncomingRecordingMessage()
        await ingester.consume(event)
        await waitForExpect(() => {
            expect(Object.keys(ingester.sessions).length).toBe(1)
            expect(ingester.sessions['1-session_id_1']).toBeDefined()
        })
    })

    it('removes sessions on destroy', async () => {
        await ingester.consume(createIncomingRecordingMessage({ team_id: 2, session_id: 'session_id_1' }))
        await ingester.consume(createIncomingRecordingMessage({ team_id: 2, session_id: 'session_id_2' }))

        expect(Object.keys(ingester.sessions).length).toBe(2)
        expect(ingester.sessions['2-session_id_1']).toBeDefined()
        expect(ingester.sessions['2-session_id_2']).toBeDefined()

        await ingester.destroySessions([['2-session_id_1', ingester.sessions['2-session_id_1']]])

        expect(Object.keys(ingester.sessions).length).toBe(1)
        expect(ingester.sessions['2-session_id_2']).toBeDefined()
    })

    it('handles multiple incoming sessions', async () => {
        const event = createIncomingRecordingMessage()
        const event2 = createIncomingRecordingMessage({
            session_id: 'session_id_2',
        })
        await Promise.all([ingester.consume(event), ingester.consume(event2)])
        expect(Object.keys(ingester.sessions).length).toBe(2)
        expect(ingester.sessions['1-session_id_1']).toBeDefined()
        expect(ingester.sessions['1-session_id_2']).toBeDefined()
    })

    it('destroys a session manager if finished', async () => {
        const event = createIncomingRecordingMessage()
        await ingester.consume(event)
        expect(ingester.sessions['1-session_id_1']).toBeDefined()
        // Force the flush
        ingester.partitionAssignments[event.metadata.partition] = {
            lastMessageTimestamp: Date.now() + defaultConfig.SESSION_RECORDING_MAX_BUFFER_AGE_SECONDS,
        }

        await ingester.flushAllReadySessions(true)

        jest.runOnlyPendingTimers() // flush timer

        expect(ingester.sessions['1-session_id_1']).not.toBeDefined()
    })

    // NOTE: Committing happens by the parent
    describe('offset committing', () => {
        const metadata = {
            partition: 1,
            topic: 'session_recording_events',
        }
        let _offset = 0
        const offset = () => _offset++

        const addMessage = (session_id: string) =>
            createIncomingRecordingMessage({ session_id }, { ...metadata, offset: offset() })

        beforeEach(() => {
            _offset = 0
        })

        const tryToCommitLatestOffset = async () => {
            await ingester.commitOffset(metadata.topic, metadata.partition, _offset)
        }

        it('should commit offsets in simple cases', async () => {
            await ingester.consume(addMessage('sid1'))
            await ingester.consume(addMessage('sid1'))
            expect(_offset).toBe(2)
            await tryToCommitLatestOffset()
            // Doesn't flush if we have a blocking session
            expect(mockCommit).toHaveBeenCalledTimes(0)
            await ingester.sessions['1-sid1']?.flush('buffer_age')
            await tryToCommitLatestOffset()

            expect(mockCommit).toHaveBeenCalledTimes(1)
            expect(mockCommit).toHaveBeenLastCalledWith({
                ...metadata,
                offset: 3,
            })
        })

        it('should commit higher values but not lower', async () => {
            await ingester.consume(addMessage('sid1'))
            await ingester.sessions['1-sid1']?.flush('buffer_age')
            await tryToCommitLatestOffset()

            expect(mockCommit).toHaveBeenCalledTimes(1)
            expect(mockCommit).toHaveBeenLastCalledWith({
                ...metadata,
                offset: 2,
            })

            const olderOffsetSomehow = addMessage('sid1')
            olderOffsetSomehow.metadata.offset = 1

            await ingester.consume(olderOffsetSomehow)
            await ingester.sessions['1-sid1']?.flush('buffer_age')
            await ingester.commitOffset(metadata.topic, metadata.partition, 1)
            expect(mockCommit).toHaveBeenCalledTimes(1)

            await ingester.consume(addMessage('sid1'))
            await ingester.sessions['1-sid1']?.flush('buffer_age')
            await tryToCommitLatestOffset()

            expect(mockCommit).toHaveBeenCalledTimes(2)
            expect(mockCommit).toHaveBeenLastCalledWith({
                ...metadata,
                offset: 4,
            })
        })

        it('should commit the lowest known offset if there is a blocking session', async () => {
            await ingester.consume(addMessage('sid1')) // 1
            await ingester.consume(addMessage('sid2')) // 2
            await ingester.consume(addMessage('sid2')) // 3
            await ingester.consume(addMessage('sid2')) // 4
            await ingester.sessions['1-sid2']?.flush('buffer_age')
            await tryToCommitLatestOffset()

            // No offsets are below the blocking one
            expect(mockCommit).not.toHaveBeenCalled()
            await ingester.sessions['1-sid1']?.flush('buffer_age')

            // Simulating the next incoming message triggers a commit for sure
            await tryToCommitLatestOffset()
            expect(mockCommit).toHaveBeenLastCalledWith({
                ...metadata,
                offset: 5,
            })
        })

        it('should commit one lower than the blocking session if that is the highest', async () => {
            await ingester.consume(addMessage('sid1')) // 1
            await ingester.consume(addMessage('sid2')) // 2
            await ingester.consume(addMessage('sid2')) // 3
            await ingester.consume(addMessage('sid2')) // 4
            await ingester.sessions['1-sid2']?.flush('buffer_age')
            await tryToCommitLatestOffset()

            // No offsets are below the blocking one
            expect(mockCommit).not.toHaveBeenCalled()
            await ingester.consume(addMessage('sid2')) // 5
            await ingester.sessions['1-sid1']?.flush('buffer_age')
            await tryToCommitLatestOffset()

            expect(mockCommit).toHaveBeenLastCalledWith({
                ...metadata,
                offset: 5, // Same as the blocking session and more than the highest commitable for sid1 (1)
            })
        })

        it('should not be affected by other partitions ', async () => {
            createIncomingRecordingMessage({ session_id: 'sid1' }, { ...metadata, partition: 2, offset: offset() })
            await ingester.consume(addMessage('sid2')) // 2
            await ingester.consume(addMessage('sid2')) // 3
            await ingester.sessions['1-sid2']?.flush('buffer_age')
            await tryToCommitLatestOffset()

            expect(mockCommit).toHaveBeenLastCalledWith({
                ...metadata,
                offset: 4,
            })
        })
    })
})
