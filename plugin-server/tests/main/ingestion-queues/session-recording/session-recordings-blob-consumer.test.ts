import { defaultConfig } from '../../../../src/config/config'
import { SessionRecordingBlobIngester } from '../../../../src/main/ingestion-queues/session-recording/session-recordings-blob-consumer'
import { Hub } from '../../../../src/types'
import { createHub } from '../../../../src/utils/db/hub'
import { createIncomingRecordingMessage } from './fixtures'

describe('ingester', () => {
    let ingester: SessionRecordingBlobIngester

    let hub: Hub
    let closeHub: () => Promise<void>

    beforeEach(async () => {
        ;[hub, closeHub] = await createHub()
    })

    afterEach(async () => {
        await closeHub()
    })

    beforeEach(() => {
        ingester = new SessionRecordingBlobIngester(hub.teamManager, defaultConfig, hub.objectStorage)
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
        expect(ingester.sessions.has('1-session_id_1')).toEqual(false)
    })

    it.each([
        [0, 0, 1000, 1000], // when no log, use configuration
        [0, 999, 1000, 1000], // when small lag, use configuration
        [0, 10 * 60 * 1000 + 1, 1000, 2000], // over ten minutes, use configuration * 2
        [0, 10 * 60 * 1000 * 2 + 1, 1000, 3000], // over twenty minutes, use configuration * 3
        [10 * 60 * 1000 * 3, 10 * 60 * 1000 * 7 + 1, 1000, 5000], // etc
        [10 * 60 * 1000 * 3, 10 * 60 * 1000 * 10 + 1, 1000, 8000], // etc
    ])(
        'uses expected flush threshold for different things',
        (kafkaNow: number, serverNow: number, configuredTolerance: number, expectedThreshold: number) => {
            expect(ingester.flushThreshold(kafkaNow, serverNow, configuredTolerance)).toEqual(expectedThreshold)
        }
    )
})
