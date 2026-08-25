import { UsageIngestionClient, UsageRecordInput } from './client'
import { UsageRecordBatch } from './usage-record-batch'

describe('UsageRecordBatch', () => {
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

    function batch(isTeamEnabled: (teamId: number) => boolean = () => true): UsageRecordBatch {
        return new UsageRecordBatch(client, { unit: 'invocations', isTeamEnabled })
    }

    it('bills a repeated identity once', async () => {
        const b = batch()
        b.add(1, 'cdp_billable_invocations', 'event:abc')
        b.add(1, 'cdp_billable_invocations', 'event:abc')
        await b.flush()

        expect(ingested[0]).toEqual([expect.objectContaining({ recordId: 'event:abc', quantity: 1 })])
    })

    it('keeps two teams that share a record ID apart', async () => {
        const b = batch()
        b.add(1, 'cdp_billable_invocations', 'event:abc')
        b.add(2, 'cdp_billable_invocations', 'event:abc')
        await b.flush()

        expect(ingested[0].map((r) => r.teamId).sort()).toEqual([1, 2])
    })

    it('keeps two usage keys apart for one team', async () => {
        const b = batch()
        b.add(1, 'events', 'uuid-1')
        b.add(1, 'ai_events', 'uuid-1')
        await b.flush()

        expect(ingested[0].map((r) => r.usageKey).sort()).toEqual(['ai_events', 'events'])
    })

    it('drops teams the matcher excludes', async () => {
        const b = batch((teamId) => teamId === 2)
        b.add(1, 'events', 'uuid-1')
        b.add(2, 'events', 'uuid-2')
        await b.flush()

        expect(ingested[0].map((r) => r.teamId)).toEqual([2])
    })

    it('does not send twice for one accumulation', async () => {
        const b = batch()
        b.add(1, 'events', 'uuid-1')
        await b.flush()
        await b.flush()

        expect(client.ingest).toHaveBeenCalledTimes(1)
    })

    it('sends nothing when no client is configured', async () => {
        const b = new UsageRecordBatch(null, { unit: 'events', isTeamEnabled: () => true })
        b.add(1, 'events', 'uuid-1')
        await b.flush()

        expect(client.ingest).not.toHaveBeenCalled()
    })

    it.each([
        ['no client', new UsageRecordBatch(null, { unit: 'events', isTeamEnabled: () => true })],
        [
            'an excluded team',
            new UsageRecordBatch({} as UsageIngestionClient, { unit: 'events', isTeamEnabled: () => false }),
        ],
    ])('flushes without waiting on acknowledgements for %s', async (_name, b) => {
        b.addAfterAcknowledgements([new Promise(() => {})], 1, 'events', 'uuid-1')

        await expect(b.flush()).resolves.toBeUndefined()
    })
})
