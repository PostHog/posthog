import { UsageIngestionClient, UsageRecordInput } from '~/common/usage-ingestion/client'
import { UsageRecordBatch } from '~/common/usage-ingestion/usage-record-batch'
import { IngestedEventInfo } from '~/ingestion/common/steps/event-processing/emit-event-step'
import { isOkResult } from '~/ingestion/framework/results'

import { createRecordEventUsageAfterIngestStep, createRecordEventUsageStep } from './usage-records-steps'

describe('usage-records-steps', () => {
    const EVENT_TIMESTAMP_MS = 1_700_000_000_000

    let ingestedUsage: UsageRecordInput[]
    let eventUsageBatch: UsageRecordBatch

    beforeEach(() => {
        jest.useFakeTimers()
        jest.setSystemTime(EVENT_TIMESTAMP_MS)
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

    async function queueEventUsage(ingested: Promise<IngestedEventInfo | null>[]): Promise<void> {
        const prepare = createRecordEventUsageStep((event) => (event === '$pageview' ? 'events' : null))
        const prepared = await prepare({
            preparedEvent: { teamId: 42, event: '$pageview', eventUuid: 'event-uuid' },
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
                recordId: 'events:event-uuid',
                teamId: 42,
                usageKey: 'events',
                unit: 'events',
                quantity: 1,
                eventTimestampMs: EVENT_TIMESTAMP_MS,
                dimensions: undefined,
            },
        ])
    })
})
