import { Code, ConnectError } from '@connectrpc/connect'
import { register } from 'prom-client'

import { UsageIngestionClient, UsageRecordInput } from './client'

describe('UsageIngestionClient', () => {
    let client: UsageIngestionClient
    let acceptedRecordIds: string[]
    let calls: number
    let headers: (Record<string, string> | undefined)[]

    const record = (teamId: number): UsageRecordInput => ({
        recordId: `record-${teamId}`,
        teamId,
        usageKey: 'feature_flag_requests',
        unit: 'requests',
        quantity: 1,
        timestampMs: 1_700_000_000_000,
    })

    const counted = async (name: string): Promise<{ labels: Record<string, unknown>; value: number }[]> => {
        const metric = register.getSingleMetric(name) as any
        const data = await metric.get()
        return data.values
    }

    beforeEach(() => {
        register.resetMetrics()
        calls = 0
        acceptedRecordIds = []
        headers = []
        client = new UsageIngestionClient({ addr: 'localhost:1', producerId: 'cdp' })
        // The transport is built in the constructor, so the stub replaces it rather than
        // standing up a server. Everything under test sits above the RPC.
        ;(client as any).client = {
            ingestBillingUsage: (_request: unknown, options?: { headers?: Record<string, string> }) => {
                calls += 1
                headers.push(options?.headers)
                return Promise.resolve({ acceptedRecordIds })
            },
        }
    })

    // The service drops a record it cannot attribute and still answers Ok, so the accepted
    // list is the only thing that says what landed. Counting the chunk instead bills nobody
    // for those records while the sent counter claims otherwise.
    test.each([
        { name: 'a partly rejected batch', teams: [7, 8, 9], accepted: [7, 9], sent: 2, rejected: 1 },
        { name: 'a fully rejected batch', teams: [7, 8], accepted: [], sent: 0, rejected: 2 },
        { name: 'a fully accepted batch', teams: [7, 8], accepted: [7, 8], sent: 2, rejected: 0 },
    ])('counts what the service accepted for $name', async ({ teams, accepted, sent, rejected }) => {
        acceptedRecordIds = accepted.map((teamId) => `record-${teamId}`)

        await client.ingest(teams.map(record))

        expect(await counted('usage_ingestion_records_sent_total')).toEqual(
            sent === 0 ? [] : [expect.objectContaining({ value: sent })]
        )
        expect(await counted('usage_ingestion_records_failed_total')).toEqual(
            rejected === 0
                ? []
                : [
                      expect.objectContaining({
                          labels: expect.objectContaining({ error_code: 'rejected' }),
                          value: rejected,
                      }),
                  ]
        )
        // The service already decided; re-sending would drop the same record again.
        expect(calls).toBe(1)
    })

    it('names the producer to the service on every request', async () => {
        // Without the header the service's request metrics read client=unknown for everyone.
        acceptedRecordIds = ['record-7']

        await client.ingest([record(7)])

        expect(headers).toEqual([{ 'x-client-name': 'cdp' }])
    })

    it('counts the whole chunk as failed when the call itself fails', async () => {
        ;(client as any).client = {
            ingestBillingUsage: () => {
                calls += 1
                return Promise.reject(new ConnectError('nope', Code.NotFound))
            },
        }

        await client.ingest([record(7), record(8)])

        expect(calls).toBe(1)
        expect(await counted('usage_ingestion_records_failed_total')).toEqual([
            expect.objectContaining({ labels: expect.objectContaining({ error_code: 'NotFound' }), value: 2 }),
        ])
    })
})
