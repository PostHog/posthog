import { defaultConfig } from '../../../../src/config/config'
import { SessionRecordingBlobIngester } from '../../../../src/main/ingestion-queues/session-recording/session-recordings-blob-consumer'
import { Hub, Team } from '../../../../src/types'
import { createHub } from '../../../../src/utils/db/hub'
import { TeamManager } from '../../../../src/worker/ingestion/team-manager'
import { createIncomingRecordingMessage } from './fixtures'

describe('ingester', () => {
    let ingester: SessionRecordingBlobIngester

    const mockTeam: Team = { id: 1 } as Team
    const mockTeamManager = {
        fetchTeam: jest.fn(() => Promise.resolve(mockTeam)),
        getTeamByToken: jest.fn(() => Promise.resolve(mockTeam)),
    } as unknown as TeamManager

    let hub: Hub
    let closeHub: () => Promise<void>

    beforeEach(async () => {
        ;[hub, closeHub] = await createHub()
    })

    afterEach(async () => {
        await closeHub()
    })

    beforeEach(() => {
        // TODO: To mock kafka or not...
        ingester = new SessionRecordingBlobIngester(hub.teamManager, hub.kafka, defaultConfig, hub.objectStorage)
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
