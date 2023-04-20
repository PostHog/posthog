import { waitForExpect } from '../../../../functional_tests/expectations'
import { defaultConfig } from '../../../../src/config/config'
import { SessionManager } from '../../../../src/main/ingestion-queues/session-recording/blob-ingester/session-manager'
import { SessionRecordingBlobIngester } from '../../../../src/main/ingestion-queues/session-recording/session-recordings-blob-consumer'
import { Hub } from '../../../../src/types'
import { createHub } from '../../../../src/utils/db/hub'
import { UUIDT } from '../../../../src/utils/utils'
import { createIncomingRecordingMessage } from './fixtures'

function countPartitions(ingesterOne: SessionRecordingBlobIngester): number {
    const partitions = new Set<number>()
    ingesterOne.sessions.forEach((session) => {
        partitions.add(session.partition)
    })
    return partitions.size
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
    })

    it('creates a new session manager if needed', async () => {
        ingesterOne = new SessionRecordingBlobIngester(hub.teamManager, hub.kafka, defaultConfig, hub.objectStorage)
        //
        // const manyEventsEachFromAUniqueSession = Array.from({ length: 100000 }).map(() => {
        //     return createIncomingRecordingMessage({ session_id: new UUIDT().toString() })
        // })

        await ingesterOne.start()
        let partitions = countPartitions(ingesterOne)
        while (partitions <= 1) {
            // consume some messages that won't immediately cause a flush
            // until the ingester has sessions on more than one partition
            await ingesterOne.consume(
                createIncomingRecordingMessage({ session_id: new UUIDT().toString(), chunk_count: 2 })
            )
            partitions = countPartitions(ingesterOne)
        }

        await waitForExpect(() => {
            expect(ingesterOne.sessions.size).toBeGreaterThan(1)
        })

        const sessionWhenOneConsumer: SessionManager | undefined = ingesterOne.sessions.values().next().value
        expect(sessionWhenOneConsumer?.flushingPaused).toEqual(false)

        ingesterTwo = new SessionRecordingBlobIngester(hub.teamManager, hub.kafka, defaultConfig, hub.objectStorage)
        void ingesterTwo.start()

        await waitForExpect(() => {
            const session: SessionManager | undefined = ingesterOne.sessions.values().next().value
            expect(session?.flushingPaused).toEqual(true)
        })

        // we expect rebalancing to complete and flushing to resume
        await waitForExpect(() => {
            const session: SessionManager | undefined = ingesterOne.sessions.values().next().value
            expect(session?.flushingPaused).toEqual(false)
        })
        // await Promise.all(
        //     manyEventsEachFromAUniqueSession.map((e) => {
        //         return hub.kafkaProducer.queueMessage({
        //             topic: 'session_recording_events',
        //             messages: [{ value: JSON.stringify(e) }],
        //         })
        //     })
        // )
        //
        // await ingesterOne.consume(event)
        // expect(ingesterOne.sessions.size).toBe(1)
        // expect(ingesterOne.sessions.has('1-session_id_1')).toEqual(true)
    })
})
