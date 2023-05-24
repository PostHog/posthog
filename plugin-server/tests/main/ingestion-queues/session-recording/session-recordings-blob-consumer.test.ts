import { defaultConfig } from '../../../../src/config/config'
import { SessionRecordingBlobIngester } from '../../../../src/main/ingestion-queues/session-recording/session-recordings-blob-consumer'
import { Hub } from '../../../../src/types'
import { createHub } from '../../../../src/utils/db/hub'
import { createIncomingRecordingMessage } from './fixtures'

const veryShortFlushInterval = 5
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
        ingester = new SessionRecordingBlobIngester(
            hub.teamManager,
            defaultConfig,
            hub.objectStorage,
            veryShortFlushInterval
        )
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
        // it is slow to start the ingester in beforeEach
        // and, it only needs starting here because we are testing the flush interval
        await ingester.start()

        const event = createIncomingRecordingMessage()
        await ingester.consume(event)
        expect(ingester.sessions.has('1-session_id_1')).toEqual(true)
        await ingester.sessions.get('1-session_id_1')?.flush('buffer_age')

        await new Promise((resolve) => setTimeout(resolve, veryShortFlushInterval))

        expect(ingester.sessions.has('1-session_id_1')).toEqual(false)
        await ingester.stop()
    })
})
