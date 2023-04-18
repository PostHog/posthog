import { createIncomingRecordingMessage } from './blob-ingester/test/fixtures'
import { SessionRecordingBlobIngester } from './session-recordings-blob-consumer'

describe('ingester', () => {
    let ingester: SessionRecordingBlobIngester
    beforeEach(() => {
        ingester = new SessionRecordingBlobIngester()
    })

    it('creates a new session manager if needed', async () => {
        const event = createIncomingRecordingMessage()
        await ingester.consume(event)
        expect(ingester.sessions.size).toBe(1)
        expect(ingester.sessions.has('1-session_id_1')).toEqual(true)
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
        await ingester.sessions.get('1-session_id_1')?.flush()
        expect(ingester.sessions.has('1-session_id_1')).toEqual(false)
    })

    it.skip('parses incoming kafka messages correctly', () => {})
})
