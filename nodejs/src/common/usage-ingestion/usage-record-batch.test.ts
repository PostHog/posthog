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
        return new UsageRecordBatch(client, {
            usageKey: 'cdp_billable_invocations',
            unit: 'invocations',
            isTeamEnabled,
        })
    }

    it('sums repeats of a record ID into one record', async () => {
        const b = batch()
        b.add(1, 'record-a', 1)
        b.add(1, 'record-a', 2)
        b.add(1, 'record-b', 1)
        await b.flush()

        expect(ingested).toHaveLength(1)
        expect(ingested[0].map((r) => [r.recordId, r.quantity])).toEqual([
            ['record-a', 3],
            ['record-b', 1],
        ])
    })

    it('drops teams the matcher excludes', async () => {
        const b = batch((teamId) => teamId === 2)
        b.add(1, 'record-a', 1)
        b.add(2, 'record-b', 1)
        await b.flush()

        expect(ingested[0].map((r) => r.teamId)).toEqual([2])
    })

    it('does not send twice for one accumulation', async () => {
        const b = batch()
        b.add(1, 'record-a', 1)
        await b.flush()
        await b.flush()

        expect(client.ingest).toHaveBeenCalledTimes(1)
    })

    it('sends nothing when no client is configured', async () => {
        const b = new UsageRecordBatch(null, { usageKey: 'k', unit: 'u', isTeamEnabled: () => true })
        b.add(1, 'record-a', 1)
        await b.flush()

        expect(client.ingest).not.toHaveBeenCalled()
    })
})
