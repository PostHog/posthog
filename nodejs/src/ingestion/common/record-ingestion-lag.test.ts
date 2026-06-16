import { Message } from 'node-rdkafka'

import { ingestionLagGauge, ingestionLagHistogram } from '../../common/metrics'
import { EventHeaders } from '../../types'
import { recordIngestionLag } from './record-ingestion-lag'

const FAKE_NOW_MS = 1702654321987 // 2023-12-15T14:32:01.987Z

function headersWithNow(now?: Date): EventHeaders {
    return {
        now,
        force_disable_person_processing: false,
        historical_migration: false,
        skip_heatmap_processing: false,
    }
}

function messageOn(partition: number, topic: string = 'test-topic'): Message {
    return { topic, partition } as Message
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

describe('recordIngestionLag', () => {
    beforeEach(() => {
        jest.useFakeTimers()
        jest.setSystemTime(FAKE_NOW_MS)
        ingestionLagGauge.reset()
        ingestionLagHistogram.reset()
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    it('records gauge and histogram lag from the capture time', async () => {
        await expectNoSamples('5')

        recordIngestionLag(headersWithNow(new Date(FAKE_NOW_MS - 5432)), messageOn(5))

        expect(await getGaugeValue('test-topic', '5')).toBe(5432)
        expect(await getHistogramCountAndSum('5')).toEqual({ count: 1, sum: 5432 })
    })

    it('measures lag against the current time, not the capture time', async () => {
        // The same captured-at, recorded one second later, yields a larger lag.
        jest.setSystemTime(FAKE_NOW_MS + 1000)

        recordIngestionLag(headersWithNow(new Date(FAKE_NOW_MS - 2000)), messageOn(5))

        expect(await getGaugeValue('test-topic', '5')).toBe(3000)
        expect(await getHistogramCountAndSum('5')).toEqual({ count: 1, sum: 3000 })
    })

    it('records each event separately, gauge keeps the last value per partition', async () => {
        recordIngestionLag(headersWithNow(new Date(FAKE_NOW_MS - 5000)), messageOn(5))
        recordIngestionLag(headersWithNow(new Date(FAKE_NOW_MS - 2000)), messageOn(5))
        recordIngestionLag(headersWithNow(new Date(FAKE_NOW_MS - 3000)), messageOn(7))

        expect(await getGaugeValue('test-topic', '5')).toBe(2000)
        expect(await getGaugeValue('test-topic', '7')).toBe(3000)
        expect(await getHistogramCountAndSum('5')).toEqual({ count: 2, sum: 7000 })
        expect(await getHistogramCountAndSum('7')).toEqual({ count: 1, sum: 3000 })
    })

    it('records partition 0 correctly in both gauge and histogram', async () => {
        recordIngestionLag(headersWithNow(new Date(FAKE_NOW_MS - 2500)), messageOn(0))

        expect(await getGaugeValue('test-topic', '0')).toBe(2500)
        expect(await getHistogramCountAndSum('0')).toEqual({ count: 1, sum: 2500 })
    })

    it('records no sample when the capture time is missing', async () => {
        await expectNoSamples('5')

        recordIngestionLag(headersWithNow(undefined), messageOn(5))

        await expectNoSamples('5')
    })
})
