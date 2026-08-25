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

    /**
     * Queues one record, starts the send, then queues a second while the first is in flight.
     * Both acknowledgements are the test's to resolve, so neither case depends on timing.
     */
    async function sendWithALateAcknowledgement(send: (b: UsageRecordBatch) => Promise<void>): Promise<void> {
        const b = batch()
        let acknowledgeFirst!: (info: object) => void
        let acknowledgeSecond!: (info: object) => void
        const first = new Promise<object>((resolve) => (acknowledgeFirst = resolve))
        const second = new Promise<object>((resolve) => (acknowledgeSecond = resolve))

        b.addAfterAcknowledgements([first], 1, 'events', 'uuid-1')
        const sending = send(b)
        b.addAfterAcknowledgements([second], 1, 'events', 'uuid-2')
        acknowledgeFirst({})
        await new Promise((resolve) => setImmediate(resolve))
        acknowledgeSecond({})
        await sending
    }

    it('drains a record acknowledged while it is already sending', async () => {
        await sendWithALateAcknowledgement((b) => b.drain())

        expect(
            ingested
                .flat()
                .map((record) => record.recordId)
                .sort()
        ).toEqual(['uuid-1', 'uuid-2'])
    })

    it('leaves a record acknowledged mid-flush for the next flush', async () => {
        // One pass, so a caller that keeps adding cannot hold a flush open forever.
        await sendWithALateAcknowledgement((b) => b.flush())

        expect(ingested.flat().map((record) => record.recordId)).toEqual(['uuid-1'])
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
