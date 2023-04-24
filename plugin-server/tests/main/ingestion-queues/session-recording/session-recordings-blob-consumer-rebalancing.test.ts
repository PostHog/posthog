import { waitForExpect } from '../../../../functional_tests/expectations'
import { defaultConfig } from '../../../../src/config/config'
import { SessionRecordingBlobIngester } from '../../../../src/main/ingestion-queues/session-recording/session-recordings-blob-consumer'
import { Hub } from '../../../../src/types'
import { createHub } from '../../../../src/utils/db/hub'
import { UUIDT } from '../../../../src/utils/utils'
import { createIncomingRecordingMessage } from './fixtures'

function assertIngesterHasExpectedPartitions(ingester: SessionRecordingBlobIngester, expectedPartitions: number[]) {
    const partitions: Set<number> = new Set()
    ingester.sessions.forEach((session) => {
        partitions.add(session.partition)
    })
    expect(Array.from(partitions)).toEqual(expectedPartitions)
}

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
        await ingesterOne?.stop()
        await ingesterTwo?.stop()
    })

    it('rebalances partitions safely from one to two consumers', async () => {
        ingesterOne = new SessionRecordingBlobIngester(hub.teamManager, defaultConfig, hub.objectStorage)

        await ingesterOne.start()

        await ingesterOne.consume(
            createIncomingRecordingMessage({ session_id: new UUIDT().toString(), chunk_count: 2 })
        )
        await ingesterOne.consume(
            createIncomingRecordingMessage({ session_id: new UUIDT().toString(), chunk_count: 2 })
        )

        await waitForExpect(() => {
            assertIngesterHasExpectedPartitions(ingesterOne, [1])
        })

        ingesterTwo = new SessionRecordingBlobIngester(hub.teamManager, defaultConfig, hub.objectStorage)
        await ingesterTwo.start()

        await waitForExpect(() => {
            assertIngesterHasExpectedPartitions(ingesterOne, [1])

            // only one partition so nothing for the new consumer to do
            assertIngesterHasExpectedPartitions(ingesterTwo, [])
        })
    })
})
