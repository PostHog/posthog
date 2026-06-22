import { ingestionLagGauge, ingestionLagHistogram } from '~/common/metrics'
import { IngestedEventInfo } from '~/ingestion/common/steps/event-processing/emit-event-step'
import { isOkResult } from '~/ingestion/framework/results'

import { RecordIngestionLagInput, createRecordIngestionLagStep } from './record-ingestion-lag'

const FAKE_NOW_MS = 1702654321987 // 2023-12-15T14:32:01.987Z

/**
 * The step records metrics in fire-and-forget `.then` reactions on the ingested
 * promises (it doesn't await them, so it can sit mid-pipeline). It registers those
 * reactions before the test awaits the same promises, so awaiting them here
 * guarantees the recording has run — no microtask-queue guessing.
 */
async function recorded(ingested: Promise<unknown>[]): Promise<void> {
    await Promise.allSettled(ingested)
}

async function getGaugeValue(topic: string, partition: string): Promise<number | undefined> {
    const metric = await ingestionLagGauge.get()
    return metric.values.find((v) => v.labels.topic === topic && v.labels.partition === partition)?.value
}

async function getHistogramCountAndSum(partition: string): Promise<{ count: number; sum: number } | null> {
    const metric = await ingestionLagHistogram.get()
    const find = (suffix: string): number | undefined =>
        metric.values.find(
            (v) => v.metricName === `ingestion_lag_ms_histogram${suffix}` && v.labels.partition === partition
        )?.value
    const count = find('_count')
    const sum = find('_sum')
    return count === undefined || sum === undefined ? null : { count, sum }
}

async function expectNoSamples(partition: string): Promise<void> {
    expect(await getGaugeValue('test-topic', partition)).toBeUndefined()
    expect(await getHistogramCountAndSum(partition)).toBeNull()
}

describe('record-ingestion-lag', () => {
    beforeEach(() => {
        jest.useFakeTimers()
        jest.setSystemTime(FAKE_NOW_MS)
        ingestionLagGauge.reset()
        ingestionLagHistogram.reset()
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    function ingestedInfo(lagMs: number, partition: number = 5): IngestedEventInfo {
        return {
            capturedAt: new Date(FAKE_NOW_MS - lagMs),
            topic: 'test-topic',
            partition,
        }
    }

    it('records gauge and histogram lag once the ingested promise resolves', async () => {
        const step = createRecordIngestionLagStep()
        await expectNoSamples('5')
        const input: RecordIngestionLagInput = { ingested: [Promise.resolve(ingestedInfo(5432))] }

        const result = await step(input)

        expect(isOkResult(result)).toBe(true)
        if (isOkResult(result)) {
            expect(result.value).toBe(input)
        }
        await recorded(input.ingested)
        expect(await getGaugeValue('test-topic', '5')).toBe(5432)
        expect(await getHistogramCountAndSum('5')).toEqual({ count: 1, sum: 5432 })
    })

    it('measures lag at ack time, not at processing time', async () => {
        const step = createRecordIngestionLagStep()
        await expectNoSamples('5')
        let ack!: (info: IngestedEventInfo) => void
        const pending = new Promise<IngestedEventInfo>((resolve) => {
            ack = resolve
        })

        await step({ ingested: [pending] })
        // Nothing recorded until the ack resolves
        expect(await getHistogramCountAndSum('5')).toBeNull()

        // The ack arrives one second after processing
        jest.setSystemTime(FAKE_NOW_MS + 1000)
        ack(ingestedInfo(2000))
        await recorded([pending])

        expect(await getGaugeValue('test-topic', '5')).toBe(3000)
        expect(await getHistogramCountAndSum('5')).toEqual({ count: 1, sum: 3000 })
    })

    it('records each ingested event separately, gauge keeps the last value per partition', async () => {
        const step = createRecordIngestionLagStep()
        await expectNoSamples('5')
        await expectNoSamples('7')
        const input: RecordIngestionLagInput = {
            ingested: [
                Promise.resolve(ingestedInfo(5000)),
                Promise.resolve(ingestedInfo(2000)),
                Promise.resolve(ingestedInfo(3000, 7)),
            ],
        }

        await step(input)
        await recorded(input.ingested)

        expect(await getGaugeValue('test-topic', '5')).toBe(2000)
        expect(await getGaugeValue('test-topic', '7')).toBe(3000)
        expect(await getHistogramCountAndSum('5')).toEqual({ count: 2, sum: 7000 })
        expect(await getHistogramCountAndSum('7')).toEqual({ count: 1, sum: 3000 })
    })

    it('records partition 0 correctly in both gauge and histogram', async () => {
        const step = createRecordIngestionLagStep()
        await expectNoSamples('0')
        const input: RecordIngestionLagInput = { ingested: [Promise.resolve(ingestedInfo(2500, 0))] }

        await step(input)
        await recorded(input.ingested)

        expect(await getGaugeValue('test-topic', '0')).toBe(2500)
        expect(await getHistogramCountAndSum('0')).toEqual({ count: 1, sum: 2500 })
    })

    it.each([
        ['the emission failed', (): Promise<IngestedEventInfo | null> => Promise.reject(new Error('produce failed'))],
        ['the event was not ingested', (): Promise<IngestedEventInfo | null> => Promise.resolve(null)],
        [
            'the capture time is missing',
            (): Promise<IngestedEventInfo | null> => Promise.resolve({ topic: 'test-topic', partition: 5 }),
        ],
    ])('records no sample when %s', async (_name, makePromise) => {
        const step = createRecordIngestionLagStep()
        await expectNoSamples('5')
        const ingested = [makePromise()]

        await step({ ingested })
        await recorded(ingested)

        await expectNoSamples('5')
    })

    it('records no sample when nothing was emitted', async () => {
        const step = createRecordIngestionLagStep()
        await expectNoSamples('5')

        await step({ ingested: [] })
        await recorded([])

        await expectNoSamples('5')
    })

    // A rejecting ingested promise must not surface as an unhandled rejection: the step
    // attaches an onRejected handler when it observes each promise. jest fails any test
    // that leaks an unhandled rejection, so exercising the reject path here is the guard.
    it('handles a rejecting ingested promise without recording a sample', async () => {
        const step = createRecordIngestionLagStep()
        await expectNoSamples('5')
        const ingested = [Promise.reject(new Error('produce failed'))]

        await step({ ingested })
        await recorded(ingested)

        await expectNoSamples('5')
    })
})
