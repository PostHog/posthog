import { Message } from 'node-rdkafka'

import { UsageIngestionClient, UsageRecordInput } from '~/common/usage-ingestion/client'

import { AI_EVENTS_USAGE_KEY, EVENTS_USAGE_KEY } from './billable-events'
import { EventUsageBatch } from './event-usage-batch'

describe('EventUsageBatch', () => {
    let ingested: UsageRecordInput[][]
    let client: UsageIngestionClient

    beforeEach(() => {
        ingested = []
        client = {
            ingest: jest.fn((records: UsageRecordInput[]) => {
                ingested.push(records)
                return Promise.resolve()
            }),
        } as unknown as UsageIngestionClient
    })

    function message(partition: number, offset: number, topic = 'events_plugin_ingestion'): Message {
        return { topic, partition, offset } as Message
    }

    it('keys the record on the consumed offset range so a replay deduplicates', async () => {
        const batch = new EventUsageBatch(client, () => true)
        batch.increment(1, EVENTS_USAGE_KEY, message(3, 100), 1)
        batch.increment(1, EVENTS_USAGE_KEY, message(3, 104), 1)
        await batch.flush()

        expect(ingested[0]).toEqual([
            expect.objectContaining({
                recordId: 'events_plugin_ingestion:3:100-104:events',
                teamId: 1,
                usageKey: EVENTS_USAGE_KEY,
                quantity: 2,
            }),
        ])
    })

    it('separates records per team, usage key and partition', async () => {
        const batch = new EventUsageBatch(client, () => true)
        batch.increment(1, EVENTS_USAGE_KEY, message(0, 1), 1)
        batch.increment(1, AI_EVENTS_USAGE_KEY, message(0, 2), 1)
        batch.increment(2, EVENTS_USAGE_KEY, message(0, 3), 1)
        batch.increment(1, EVENTS_USAGE_KEY, message(1, 4), 1)
        await batch.flush()

        expect(ingested[0].map((r) => r.recordId)).toEqual([
            'events_plugin_ingestion:0:1-1:events',
            'events_plugin_ingestion:0:2-2:ai_events',
            'events_plugin_ingestion:0:3-3:events',
            'events_plugin_ingestion:1:4-4:events',
        ])
    })

    it('drops teams the matcher excludes', async () => {
        const batch = new EventUsageBatch(client, (teamId) => teamId === 2)
        batch.increment(1, EVENTS_USAGE_KEY, message(0, 1), 1)
        batch.increment(2, EVENTS_USAGE_KEY, message(0, 2), 1)
        await batch.flush()

        expect(ingested[0].map((r) => r.teamId)).toEqual([2])
    })

    it('sends nothing when no client is configured', async () => {
        const batch = new EventUsageBatch(null, () => true)
        batch.increment(1, EVENTS_USAGE_KEY, message(0, 1), 1)
        await batch.flush()

        expect(client.ingest).not.toHaveBeenCalled()
    })
})
