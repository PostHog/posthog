import { mkdirSync, rmSync } from 'node:fs'
import path from 'path'

import { defaultConfig } from '../../../../src/config/config'
import { SessionRecordingBlobIngester } from '../../../../src/main/ingestion-queues/session-recording/session-recordings-blob-consumer'
import { Hub, PluginsServerConfig } from '../../../../src/types'
import { createHub } from '../../../../src/utils/db/hub'
import { createIncomingRecordingMessage } from './fixtures'

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
        ingester = new SessionRecordingBlobIngester(
            hub.teamManager,
            defaultConfig,
            hub.objectStorage,
            veryShortFlushInterval
        )
        await ingester.start()
    })

    afterEach(async () => {
        await ingester.stop()
        await closeHub()
    })

    afterAll(() => {
        rmSync(config.SESSION_RECORDING_LOCAL_DIRECTORY, { recursive: true, force: true })
    })

    it('creates a new session manager if needed', async () => {
        const event = createIncomingRecordingMessage()
        await ingester.consume(event)
        expect(ingester.sessions.size).toBe(1)
        expect(ingester.sessions.has('1-session_id_1')).toEqual(true)
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

        await new Promise((resolve) => setTimeout(resolve, veryShortFlushInterval))

        expect(ingester.sessions.has('1-session_id_1')).toEqual(false)
    })
})
