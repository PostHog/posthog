import { waitForExpect } from '../../../../functional_tests/expectations'
import { defaultConfig } from '../../../../src/config/config'
import { SessionRecordingBlobIngester } from '../../../../src/main/ingestion-queues/session-recording/session-recordings-blob-consumer'
import { Hub } from '../../../../src/types'
import { createHub } from '../../../../src/utils/db/hub'
import { UUIDT } from '../../../../src/utils/utils'
import { createIncomingRecordingMessage } from './fixtures'

describe('ingester rebalancing tests', () => {
    let ingesterOne: SessionRecordingBlobIngester
    let ingesterTwo: SessionRecordingBlobIngester

    let hub: Hub
    let closeHub: () => Promise<void>

    beforeEach(async () => {
        ;[hub, closeHub] = await createHub()
    })

    afterEach(async () => {
        await closeHub()
    })

    it('rebalances partitions safely from one to two consumers', async () => {
        ingesterOne = new SessionRecordingBlobIngester(hub.teamManager, defaultConfig, hub.objectStorage)

        await ingesterOne.start()

        createIncomingRecordingMessage({ session_id: new UUIDT().toString(), chunk_count: 2 })

        await waitForExpect(() => {
            expect(ingesterOne.sessions.size).toBeGreaterThan(1)
        })

        ingesterTwo = new SessionRecordingBlobIngester(hub.teamManager, defaultConfig, hub.objectStorage)
        void ingesterTwo.start()

        expect(1).toBe('this test is not finished')
    })
})
