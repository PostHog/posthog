import { register } from 'prom-client'

import { logger } from '~/common/utils/logger'

import { FedSubBatch, InFlightSubBatches } from './in-flight-sub-batches'

const TIMEOUT_MS = 100

function subBatch(streamId: number, seq: number, offsets: number[] = [seq]): FedSubBatch {
    return {
        streamId,
        seq,
        consumerId: `consumer-${streamId}`,
        streamEpoch: '1',
        assignmentEpoch: '1',
        messages: offsets.map((offset) => ({
            topic: 'events',
            partition: 0,
            offset,
            timestamp: 0,
            key: 'k',
            value: '{}',
            headers: {},
        })),
    }
}

async function metricValue(name: string): Promise<number> {
    const metric = register.getSingleMetric(name)
    return (await metric!.get()).values[0]?.value ?? 0
}

async function accountingSnapshot(): Promise<Record<string, number>> {
    const names = [
        'ingestion_api_batches_in_flight',
        'ingestion_api_events_in_flight',
        'ingestion_api_batches_processed_total',
        'ingestion_api_messages_processed_total',
        'ingestion_api_batch_errors_total',
    ]
    return Object.fromEntries(await Promise.all(names.map(async (name) => [name, await metricValue(name)])))
}

async function accountingDelta(before: Record<string, number>): Promise<Record<string, number>> {
    const after = await accountingSnapshot()
    return Object.fromEntries(Object.entries(after).map(([name, value]) => [name, value - before[name]]))
}

function stuckLogs(errorLog: jest.SpyInstance): unknown[] {
    return errorLog.mock.calls
        .filter(([, message]) => message === 'WorkerIngest sub-batch stuck')
        .map(([, , fields]) => fields)
}

describe('InFlightSubBatches', () => {
    let inFlight: InFlightSubBatches
    let errorLog: jest.SpyInstance

    beforeEach(() => {
        jest.useFakeTimers({ now: 0 })
        errorLog = jest.spyOn(logger, 'error')
        inFlight = new InFlightSubBatches(TIMEOUT_MS)
    })

    afterEach(() => {
        jest.useRealTimers()
        jest.restoreAllMocks()
    })

    it.each([
        {
            outcome: 'ok' as const,
            expected: {
                ingestion_api_batches_in_flight: 0,
                ingestion_api_events_in_flight: 0,
                ingestion_api_batches_processed_total: 1,
                ingestion_api_messages_processed_total: 2,
                ingestion_api_batch_errors_total: 0,
            },
        },
        {
            outcome: 'failed' as const,
            expected: {
                ingestion_api_batches_in_flight: 0,
                ingestion_api_events_in_flight: 0,
                ingestion_api_batches_processed_total: 0,
                ingestion_api_messages_processed_total: 0,
                ingestion_api_batch_errors_total: 1,
            },
        },
    ])('holds a fed sub-batch in flight until it settles $outcome', async ({ outcome, expected }) => {
        const before = await accountingSnapshot()

        inFlight.onFed(subBatch(1, 1, [10, 11, 12]))
        expect(inFlight.size).toBe(1)
        expect(await accountingDelta(before)).toMatchObject({
            ingestion_api_batches_in_flight: 1,
            ingestion_api_events_in_flight: 3,
        })

        inFlight.onSettled(1, 1, outcome, 2)
        inFlight.onSettled(1, 1, outcome, 2)

        expect(inFlight.size).toBe(0)
        expect(await accountingDelta(before)).toEqual(expected)
    })

    it('keeps sub-batches of different streams apart even when their seqs match', () => {
        inFlight.onFed(subBatch(1, 1))
        inFlight.onFed(subBatch(2, 1))
        inFlight.onFed(subBatch(2, 2))
        inFlight.onStreamEnded(1)
        inFlight.onSettled(2, 1, 'ok', 1)
        jest.setSystemTime(TIMEOUT_MS + 1)

        const stuck = inFlight.findStuck(Date.now())
        inFlight.reportStuck(stuck)

        expect(inFlight.size).toBe(2)
        expect(stuck.map(({ key, streamId }) => ({ key, streamId }))).toEqual([
            { key: '1:1', streamId: 1 },
            { key: '2:2', streamId: 2 },
        ])
        expect(stuckLogs(errorLog)).toEqual([
            expect.objectContaining({ key: '1:1', streamOpen: false }),
            expect.objectContaining({ key: '2:2', streamOpen: true }),
        ])
    })

    it('reports a sub-batch as stuck only once it is in flight longer than the timeout', () => {
        inFlight.onFed(subBatch(1, 1))
        jest.setSystemTime(40)
        inFlight.onFed(subBatch(1, 2))

        expect(inFlight.findStuck(TIMEOUT_MS)).toEqual([])
        expect(inFlight.findStuck(TIMEOUT_MS + 1)).toEqual([{ key: '1:1', streamId: 1, inFlightMs: TIMEOUT_MS + 1 }])
        expect(inFlight.findStuck(140 + 1).map(({ key }) => key)).toEqual(['1:1', '1:2'])
    })

    it('tracks the oldest in-flight age and drops it to 0 once everything settles', async () => {
        inFlight.onFed(subBatch(1, 1))
        jest.setSystemTime(30)
        inFlight.onFed(subBatch(1, 2))

        inFlight.findStuck(50)
        expect(await metricValue('ingestion_api_grpc_oldest_in_flight_batch_age_seconds')).toBe(0.05)

        inFlight.onSettled(1, 1, 'ok', 1)
        inFlight.findStuck(50)
        expect(await metricValue('ingestion_api_grpc_oldest_in_flight_batch_age_seconds')).toBe(0.02)

        inFlight.onSettled(1, 2, 'ok', 1)
        inFlight.findStuck(50)
        expect(await metricValue('ingestion_api_grpc_oldest_in_flight_batch_age_seconds')).toBe(0)
    })

    it('never reports stuck sub-batches when the timeout is 0, but still tracks the oldest age', async () => {
        inFlight = new InFlightSubBatches(0)
        inFlight.onFed(subBatch(1, 1))

        expect(inFlight.findStuck(600_000)).toEqual([])
        expect(await metricValue('ingestion_api_grpc_oldest_in_flight_batch_age_seconds')).toBe(600)
    })

    it('logs each stuck sub-batch once per trip and skips one that settled since it was found', async () => {
        const trips = await metricValue('ingestion_api_grpc_stuck_batches_total')
        inFlight.onFed(subBatch(1, 1, [10, 11]))
        inFlight.onFed(subBatch(2, 1, [20]))
        inFlight.onFed(subBatch(3, 1, [30]))
        jest.setSystemTime(TIMEOUT_MS + 1)
        const stuck = inFlight.findStuck(Date.now())

        inFlight.onSettled(3, 1, 'ok', 1)
        inFlight.reportStuck(stuck)

        expect(await metricValue('ingestion_api_grpc_stuck_batches_total')).toBe(trips + 1)
        expect(stuckLogs(errorLog)).toEqual([
            {
                key: '1:1',
                inFlightMs: TIMEOUT_MS + 1,
                consumerId: 'consumer-1',
                streamEpoch: '1',
                assignmentEpoch: '1',
                count: 2,
                offsets: ['events[0]:10-11'],
                streamOpen: true,
            },
            expect.objectContaining({ key: '2:1', count: 1, offsets: ['events[0]:20'] }),
        ])
    })

    it.each([
        { timeoutMs: 0, checkIntervalMs: 10_000 },
        { timeoutMs: 200, checkIntervalMs: 50 },
        { timeoutMs: 300_000, checkIntervalMs: 10_000 },
    ])('checks every $checkIntervalMs ms for a timeout of $timeoutMs ms', ({ timeoutMs, checkIntervalMs }) => {
        expect(new InFlightSubBatches(timeoutMs).checkIntervalMs).toBe(checkIntervalMs)
    })
})
