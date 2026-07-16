import { MessageHeader } from 'node-rdkafka'

import { ingestionLagGauge, ingestionLagHistogram } from '~/common/metrics'

import { LagReportableMessage, SessionReplayLagReporter } from './session-replay-lag-reporter'

const FAKE_NOW_MS = 1702654321987 // 2023-12-15T14:32:01.987Z
const TEST_TOPIC = 'test-topic'

async function getGaugeValue(partition: string): Promise<number | undefined> {
    const metric = await ingestionLagGauge.get()
    return metric.values.find((v) => v.labels.topic === TEST_TOPIC && v.labels.partition === partition)?.value
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

function message(partition: number, headers?: MessageHeader[]): LagReportableMessage {
    return { partition, headers }
}

function nowHeader(capturedAtMs: number): MessageHeader[] {
    return [{ now: Buffer.from(new Date(capturedAtMs).toISOString()) }]
}

describe('SessionReplayLagReporter', () => {
    let reporter: SessionReplayLagReporter

    beforeEach(() => {
        jest.useFakeTimers()
        jest.setSystemTime(FAKE_NOW_MS)
        ingestionLagGauge.reset()
        ingestionLagHistogram.reset()
        reporter = new SessionReplayLagReporter(TEST_TOPIC)
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    it('observes lag from capture time to flush time and reports it per partition', async () => {
        reporter.record([message(0, nowHeader(FAKE_NOW_MS - 5000)), message(0, nowHeader(FAKE_NOW_MS - 3000))])
        reporter.record([message(1, nowHeader(FAKE_NOW_MS - 2000))])

        // Nothing is observed until the batch is durably flushed.
        expect(await getGaugeValue('0')).toBeUndefined()

        // The flush happens two seconds after the last record — lag is measured against flush time.
        jest.setSystemTime(FAKE_NOW_MS + 2000)
        reporter.flush()

        // Gauge keeps the last sample per partition; the histogram aggregates every sample.
        expect(await getGaugeValue('0')).toBe(5000)
        expect(await getHistogramCountAndSum('0')).toEqual({ count: 2, sum: 12000 })
        expect(await getGaugeValue('1')).toBe(4000)
        expect(await getHistogramCountAndSum('1')).toEqual({ count: 1, sum: 4000 })
    })

    it('clears pending timestamps after a flush so the next flush does not re-report them', async () => {
        reporter.record([message(0, nowHeader(FAKE_NOW_MS - 5000))])
        reporter.flush()
        expect(await getHistogramCountAndSum('0')).toEqual({ count: 1, sum: 5000 })

        reporter.flush()

        // A second flush with nothing recorded since must not add another sample.
        expect(await getHistogramCountAndSum('0')).toEqual({ count: 1, sum: 5000 })
    })

    it('is a no-op when flushing with nothing pending', async () => {
        reporter.flush()

        expect(await getGaugeValue('0')).toBeUndefined()
        expect(await getHistogramCountAndSum('0')).toBeNull()
    })

    it.each<{ name: string; headers?: MessageHeader[] }>([
        { name: 'no headers at all', headers: undefined },
        { name: 'no now header', headers: [{ token: Buffer.from('t') }] },
        { name: 'an unparseable now value', headers: [{ now: Buffer.from('not-a-date') }] },
    ])('skips a message with $name', async ({ headers }) => {
        reporter.record([message(0, headers)])
        reporter.flush()

        expect(await getGaugeValue('0')).toBeUndefined()
        expect(await getHistogramCountAndSum('0')).toBeNull()
    })
})
