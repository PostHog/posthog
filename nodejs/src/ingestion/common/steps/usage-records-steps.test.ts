import { UsageIngestionClient, UsageRecordInput } from '~/common/usage-ingestion/client'
import { UsageRecordBatch } from '~/common/usage-ingestion/usage-record-batch'
import { IngestedEventInfo } from '~/ingestion/common/steps/event-processing/emit-event-step'
import { isOkResult } from '~/ingestion/framework/results'

import { createRecordEventUsageAfterIngestStep, createRecordEventUsageStep } from './usage-records-steps'

describe('usage-records-steps', () => {
    const FLUSH_TIMESTAMP_MS = 1_700_000_000_000

    let ingestedUsage: UsageRecordInput[]
    let eventUsageBatch: UsageRecordBatch

    beforeEach(() => {
        jest.useFakeTimers()
        jest.setSystemTime(FLUSH_TIMESTAMP_MS)
        ingestedUsage = []
        const usageClient = {
            ingest: jest.fn((records: UsageRecordInput[]) => {
                ingestedUsage.push(...records)
                return Promise.resolve()
            }),
        } as unknown as UsageIngestionClient
        eventUsageBatch = new UsageRecordBatch(usageClient, { unit: 'events', isTeamEnabled: () => true })
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    async function queueEventUsage(
        ingested: Promise<IngestedEventInfo | null>[],
        event: Partial<{ event: string; eventUuid: string; distinctId: string }> = {}
    ): Promise<void> {
        const prepare = createRecordEventUsageStep(() => 'events')
        const prepared = await prepare({
            preparedEvent: {
                teamId: 42,
                event: '$pageview',
                eventUuid: 'event-uuid',
                distinctId: 'user-7',
                timestamp: '2026-06-15T23:55:00.000Z',
                ...event,
            },
            eventUsageBatch,
        })
        expect(isOkResult(prepared)).toBe(true)
        if (!isOkResult(prepared)) {
            throw new Error('expected usage preparation to succeed')
        }

        const recordAfterIngest = createRecordEventUsageAfterIngestStep()
        await recordAfterIngest({ ...prepared.value, ingested })
    }

    it.each([
        [
            'Kafka rejects the write',
            (): Promise<IngestedEventInfo | null> => Promise.reject(new Error('Kafka unavailable')),
        ],
        ['Kafka declines the event', (): Promise<IngestedEventInfo | null> => Promise.resolve(null)],
    ])('does not report usage when %s', async (_name, acknowledgement) => {
        await queueEventUsage([acknowledgement()])

        await eventUsageBatch.flush()

        expect(ingestedUsage).toEqual([])
    })

    it.each([
        ['ordinary values', {}],
        [
            'the longest event name and distinct ID a client can send',
            { event: 'e'.repeat(200), distinctId: 'd'.repeat(400) },
        ],
    ])('keeps the record ID inside the service identifier limit with %s', async (_name, event) => {
        await queueEventUsage([Promise.resolve({ topic: 'events', partition: 0 })], event)

        await eventUsageBatch.flush()

        expect(ingestedUsage[0].recordId).toMatch(/^2026-06-15:[0-9a-f]{32}$/)
    })

    it.each([
        ['distinct ID', { distinctId: 'user-8' }],
        ['event name', { event: '$autocapture' }],
        ['UUID', { eventUuid: 'other-uuid' }],
    ])('bills two events that differ only in %s separately', async (_name, event) => {
        const acknowledged = (): Promise<IngestedEventInfo> => Promise.resolve({ topic: 'events', partition: 0 })
        await queueEventUsage([acknowledged()])
        await queueEventUsage([acknowledged()], event)

        await eventUsageBatch.flush()

        expect(new Set(ingestedUsage.map((record) => record.recordId)).size).toBe(2)
    })

    it('bills two events apart when only the position of a newline differs', async () => {
        const acknowledged = (): Promise<IngestedEventInfo> => Promise.resolve({ topic: 'events', partition: 0 })
        await queueEventUsage([acknowledged()], { event: 'a\nb', distinctId: 'c' })
        await queueEventUsage([acknowledged()], { event: 'a', distinctId: 'b\nc' })

        await eventUsageBatch.flush()

        expect(new Set(ingestedUsage.map((record) => record.recordId)).size).toBe(2)
    })

    it('reports the event usage payload only after Kafka acknowledges the write', async () => {
        let acknowledgeKafka!: (info: IngestedEventInfo) => void
        const kafkaAcknowledgement = new Promise<IngestedEventInfo>((resolve) => {
            acknowledgeKafka = resolve
        })

        await queueEventUsage([kafkaAcknowledgement])
        const flush = eventUsageBatch.flush()
        await expect(Promise.resolve()).resolves.toBeUndefined()
        expect(ingestedUsage).toEqual([])

        acknowledgeKafka({ topic: 'events', partition: 0 })
        await flush

        expect(ingestedUsage).toEqual([
            {
                recordId: expect.stringMatching(/^2026-06-15:[0-9a-f]{32}$/),
                teamId: 42,
                usageKey: 'events',
                unit: 'events',
                quantity: 1,
                timestampMs: FLUSH_TIMESTAMP_MS,
                dimensions: undefined,
            },
        ])
    })
})
