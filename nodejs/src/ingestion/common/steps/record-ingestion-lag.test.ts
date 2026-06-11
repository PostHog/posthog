import { Message } from 'node-rdkafka'

import { createTestMessage } from '../../../../tests/helpers/kafka-message'
import { ingestionLagGauge, ingestionLagHistogram } from '../../../common/metrics'
import { createContext } from '../../pipelines/helpers'
import { drop, isOkResult, ok } from '../../pipelines/results'
import { RecordIngestionLagInput, createRecordIngestionLagStep } from './record-ingestion-lag'

const FAKE_NOW_MS = 1702654321987 // 2023-12-15T14:32:01.987Z

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

    function createMessageWithNow(lagMs: number, overrides: Partial<Message> = {}): Message {
        return createTestMessage({
            headers: [{ now: Buffer.from(new Date(FAKE_NOW_MS - lagMs).toISOString()) }],
            ...overrides,
        })
    }

    function createInput(messages: { message: Message; isOk?: boolean }[]): RecordIngestionLagInput {
        return {
            elements: messages.map(({ message, isOk = true }) =>
                createContext(isOk ? ok<unknown>(undefined) : drop<unknown>('test-drop'), { message })
            ),
        }
    }

    it('records gauge and histogram lag for ok elements from the now header', async () => {
        const step = createRecordIngestionLagStep()
        const input = createInput([{ message: createMessageWithNow(5432) }])

        const result = await step(input)

        expect(isOkResult(result)).toBe(true)
        if (isOkResult(result)) {
            expect(result.value).toBe(input)
        }
        expect(await getGaugeValue('test-topic', '5')).toBe(5432)
        expect(await getHistogramCountAndSum('5')).toEqual({ count: 1, sum: 5432 })
    })

    it('records each element separately, gauge keeps the last value per partition', async () => {
        const step = createRecordIngestionLagStep()
        const input = createInput([
            { message: createMessageWithNow(5000) },
            { message: createMessageWithNow(2000) },
            { message: createMessageWithNow(3000, { partition: 7 }) },
        ])

        await step(input)

        expect(await getGaugeValue('test-topic', '5')).toBe(2000)
        expect(await getGaugeValue('test-topic', '7')).toBe(3000)
        expect(await getHistogramCountAndSum('5')).toEqual({ count: 2, sum: 7000 })
        expect(await getHistogramCountAndSum('7')).toEqual({ count: 1, sum: 3000 })
    })

    it('skips non-ok elements', async () => {
        const step = createRecordIngestionLagStep()
        const input = createInput([{ message: createMessageWithNow(5000), isOk: false }])

        await step(input)

        expect(await getGaugeValue('test-topic', '5')).toBeUndefined()
        expect(await getHistogramCountAndSum('5')).toBeNull()
    })

    it.each([
        ['no headers', createTestMessage({ headers: undefined })],
        ['no now header', createTestMessage({ headers: [{ token: Buffer.from('test-token') }] })],
        ['unparseable now header', createTestMessage({ headers: [{ now: Buffer.from('not-a-date') }] })],
    ])('skips elements with %s', async (_name, message) => {
        const step = createRecordIngestionLagStep()
        const input = createInput([{ message }])

        await step(input)

        expect(await getGaugeValue('test-topic', '5')).toBeUndefined()
        expect(await getHistogramCountAndSum('5')).toBeNull()
    })
})
