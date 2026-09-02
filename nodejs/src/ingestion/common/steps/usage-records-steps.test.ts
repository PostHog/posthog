import { DateTime } from 'luxon'

import { UsageIngestionClient, UsageRecordInput } from '~/common/usage-ingestion/client'
import { UsageRecordBatch } from '~/common/usage-ingestion/usage-record-batch'
import { IngestedEventInfo } from '~/ingestion/common/steps/event-processing/emit-event-step'
import { isOkResult } from '~/ingestion/framework/results'
import { Person } from '~/types'

import { createRecordEventUsageAfterIngestStep, createRecordEventUsageStep } from './usage-records-steps'

const forceUpgradedPerson = (): Person => ({
    team_id: 42,
    properties: {},
    uuid: 'person-uuid',
    created_at: DateTime.fromISO('2026-06-01T00:00:00.000Z'),
    force_upgrade: true,
})

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
        event: Partial<{ event: string; eventUuid: string; distinctId: string }> = {},
        personProcessing: { processPerson?: boolean; person?: Person } = {}
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
            ...personProcessing,
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
            },
        ])
    })

    // The meters have to match `person_mode` in the nightly report's two billable-event queries,
    // which count `full` and `force_upgrade` as enhanced and `propertyless` as not. A force upgrade
    // only happens when the client asked for propertyless, so it is the case that breaks if the
    // step goes back to reading `processPerson` alone.
    it.each([
        ['full', { processPerson: true }, ['events', 'enhanced_person_events']],
        ['propertyless', { processPerson: false }, ['events']],
        [
            'force_upgrade',
            { processPerson: false, person: forceUpgradedPerson() },
            ['events', 'enhanced_person_events'],
        ],
    ])('bills %s person processing under %j', async (_mode, personProcessing, expectedUsageKeys) => {
        await queueEventUsage([Promise.resolve({ topic: 'events', partition: 0 })], {}, personProcessing)

        await eventUsageBatch.flush()

        expect(ingestedUsage.map((record) => record.usageKey)).toEqual(expectedUsageKeys)
        // One event, so both meters share the identity and are told apart only by the usage key.
        expect(new Set(ingestedUsage.map((record) => record.recordId)).size).toBe(1)
    })
})
