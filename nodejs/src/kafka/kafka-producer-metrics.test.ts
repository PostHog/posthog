import { Counter, Gauge, register } from 'prom-client'

import {
    ProducerStatsTracker,
    kafkaProducerAnyBrokersDown,
    kafkaProducerBrokerConnected,
    kafkaProducerBrokerDisconnectsTotal,
    kafkaProducerBrokerInflightRequests,
    kafkaProducerBrokerOutbufMessages,
    kafkaProducerBrokerOutbufRequests,
    kafkaProducerBrokerRequestTimeoutsTotal,
    kafkaProducerBrokerRttMicroseconds,
    kafkaProducerBrokerRxErrorsTotal,
    kafkaProducerBrokerThrottleMilliseconds,
    kafkaProducerBrokerTxErrorsTotal,
    kafkaProducerBrokerTxRetriesTotal,
    kafkaProducerCallbackQueueDepth,
    kafkaProducerQueueBytes,
    kafkaProducerQueueMaxBytes,
    kafkaProducerQueueMaxMessages,
    kafkaProducerQueueMessages,
    kafkaProducerTopicBatchCountAvg,
    kafkaProducerTopicBatchSizeBytesAvg,
} from './kafka-producer-metrics'

async function gaugeValue(metric: Gauge<string>, labels: Record<string, string>): Promise<number | undefined> {
    const snapshot = await metric.get()
    return snapshot.values.find((v) => JSON.stringify(v.labels) === JSON.stringify(labels))?.value
}

async function counterValue(metric: Counter<string>, labels: Record<string, string>): Promise<number | undefined> {
    const snapshot = await metric.get()
    return snapshot.values.find((v) => JSON.stringify(v.labels) === JSON.stringify(labels))?.value
}

function makeStats(overrides: Record<string, any> = {}): string {
    return JSON.stringify({
        msg_cnt: 10,
        msg_size: 1024,
        msg_max: 100_000,
        msg_size_max: 1_073_741_824,
        replyq: 0,
        brokers: {},
        topics: {},
        ...overrides,
    })
}

function makeBroker(overrides: Record<string, any> = {}): any {
    return {
        name: 'kafka-1:9092/1',
        nodeid: 1,
        state: 'UP',
        outbuf_cnt: 0,
        outbuf_msg_cnt: 0,
        waitresp_cnt: 0,
        tx: 0,
        txerrs: 0,
        txretries: 0,
        req_timeouts: 0,
        disconnects: 0,
        rxerrs: 0,
        rtt: { p50: 0, p90: 0, p95: 0, p99: 0 },
        throttle: { p50: 0, p90: 0, p95: 0, p99: 0 },
        ...overrides,
    }
}

describe('ProducerStatsTracker', () => {
    beforeEach(() => {
        register.resetMetrics()
    })

    it('sets top-level queue gauges', async () => {
        const tracker = new ProducerStatsTracker('DEFAULT')

        tracker.track(makeStats({ msg_cnt: 42, msg_size: 9000, msg_max: 100_000, msg_size_max: 1_000_000, replyq: 7 }))

        const labels = { producer_name: 'DEFAULT' }
        expect(await gaugeValue(kafkaProducerQueueMessages, labels)).toBe(42)
        expect(await gaugeValue(kafkaProducerQueueBytes, labels)).toBe(9000)
        expect(await gaugeValue(kafkaProducerQueueMaxMessages, labels)).toBe(100_000)
        expect(await gaugeValue(kafkaProducerQueueMaxBytes, labels)).toBe(1_000_000)
        expect(await gaugeValue(kafkaProducerCallbackQueueDepth, labels)).toBe(7)
    })

    it('sets per-broker gauges including state, outbuf, rtt and throttle quantiles', async () => {
        const tracker = new ProducerStatsTracker('DEFAULT')

        tracker.track(
            makeStats({
                brokers: {
                    'kafka-1:9092/1': makeBroker({
                        state: 'UP',
                        outbuf_cnt: 2,
                        outbuf_msg_cnt: 5,
                        waitresp_cnt: 3,
                        rtt: { p50: 100, p90: 500, p95: 800, p99: 1234 },
                        throttle: { p50: 0, p90: 10, p95: 25, p99: 50 },
                    }),
                },
            })
        )

        const labels = { producer_name: 'DEFAULT', broker: 'kafka-1:9092/1' }
        expect(await gaugeValue(kafkaProducerBrokerConnected, labels)).toBe(1)
        expect(await gaugeValue(kafkaProducerBrokerOutbufMessages, labels)).toBe(5)
        expect(await gaugeValue(kafkaProducerBrokerOutbufRequests, labels)).toBe(2)
        expect(await gaugeValue(kafkaProducerBrokerInflightRequests, labels)).toBe(3)
        expect(await gaugeValue(kafkaProducerBrokerRttMicroseconds, { ...labels, quantile: 'p50' })).toBe(100)
        expect(await gaugeValue(kafkaProducerBrokerRttMicroseconds, { ...labels, quantile: 'p99' })).toBe(1234)
        expect(await gaugeValue(kafkaProducerBrokerThrottleMilliseconds, { ...labels, quantile: 'p99' })).toBe(50)
    })

    it('flags any broker not UP via kafkaProducerAnyBrokersDown', async () => {
        const tracker = new ProducerStatsTracker('DEFAULT')

        tracker.track(
            makeStats({
                brokers: {
                    'kafka-1:9092/1': makeBroker({ state: 'UP' }),
                    'kafka-2:9092/2': makeBroker({ state: 'DOWN' }),
                },
            })
        )

        expect(await gaugeValue(kafkaProducerAnyBrokersDown, { producer_name: 'DEFAULT' })).toBe(1)
        expect(
            await gaugeValue(kafkaProducerBrokerConnected, { producer_name: 'DEFAULT', broker: 'kafka-2:9092/2' })
        ).toBe(0)
    })

    it('sets per-topic batching gauges', async () => {
        const tracker = new ProducerStatsTracker('DEFAULT')

        tracker.track(
            makeStats({
                topics: {
                    events_plugin_ingestion: { batchsize: { avg: 8192 }, batchcnt: { avg: 42 } },
                },
            })
        )

        const labels = { producer_name: 'DEFAULT', topic: 'events_plugin_ingestion' }
        expect(await gaugeValue(kafkaProducerTopicBatchSizeBytesAvg, labels)).toBe(8192)
        expect(await gaugeValue(kafkaProducerTopicBatchCountAvg, labels)).toBe(42)
    })

    it('skips the first observation for cumulative counters to avoid spurious jumps', async () => {
        const tracker = new ProducerStatsTracker('DEFAULT')
        const labels = { producer_name: 'DEFAULT', broker: 'kafka-1:9092/1' }

        tracker.track(
            makeStats({
                brokers: {
                    'kafka-1:9092/1': makeBroker({ txerrs: 7, txretries: 3, req_timeouts: 2, disconnects: 1 }),
                },
            })
        )

        expect(await counterValue(kafkaProducerBrokerTxErrorsTotal, labels)).toBeUndefined()
        expect(await counterValue(kafkaProducerBrokerTxRetriesTotal, labels)).toBeUndefined()
        expect(await counterValue(kafkaProducerBrokerRequestTimeoutsTotal, labels)).toBeUndefined()
        expect(await counterValue(kafkaProducerBrokerDisconnectsTotal, labels)).toBeUndefined()
    })

    it('increments counters by delta between observations', async () => {
        const tracker = new ProducerStatsTracker('DEFAULT')
        const labels = { producer_name: 'DEFAULT', broker: 'kafka-1:9092/1' }

        tracker.track(
            makeStats({
                brokers: {
                    'kafka-1:9092/1': makeBroker({ txerrs: 5, txretries: 10, req_timeouts: 1, rxerrs: 4 }),
                },
            })
        )
        tracker.track(
            makeStats({
                brokers: {
                    'kafka-1:9092/1': makeBroker({ txerrs: 8, txretries: 12, req_timeouts: 1, rxerrs: 9 }),
                },
            })
        )

        expect(await counterValue(kafkaProducerBrokerTxErrorsTotal, labels)).toBe(3)
        expect(await counterValue(kafkaProducerBrokerTxRetriesTotal, labels)).toBe(2)
        expect(await counterValue(kafkaProducerBrokerRxErrorsTotal, labels)).toBe(5)
        expect(await counterValue(kafkaProducerBrokerRequestTimeoutsTotal, labels)).toBeUndefined()
    })

    it('does not decrement counters when librdkafka resets (safety net)', async () => {
        const tracker = new ProducerStatsTracker('DEFAULT')
        const labels = { producer_name: 'DEFAULT', broker: 'kafka-1:9092/1' }

        tracker.track(makeStats({ brokers: { 'kafka-1:9092/1': makeBroker({ txerrs: 10 }) } }))
        tracker.track(makeStats({ brokers: { 'kafka-1:9092/1': makeBroker({ txerrs: 15 }) } }))
        tracker.track(makeStats({ brokers: { 'kafka-1:9092/1': makeBroker({ txerrs: 5 }) } }))
        tracker.track(makeStats({ brokers: { 'kafka-1:9092/1': makeBroker({ txerrs: 8 }) } }))

        expect(await counterValue(kafkaProducerBrokerTxErrorsTotal, labels)).toBe(5 + 3)
    })

    it('tracks deltas independently per broker', async () => {
        const tracker = new ProducerStatsTracker('DEFAULT')

        tracker.track(
            makeStats({
                brokers: {
                    'kafka-1:9092/1': makeBroker({ txerrs: 1 }),
                    'kafka-2:9092/2': makeBroker({ txerrs: 100 }),
                },
            })
        )
        tracker.track(
            makeStats({
                brokers: {
                    'kafka-1:9092/1': makeBroker({ txerrs: 3 }),
                    'kafka-2:9092/2': makeBroker({ txerrs: 105 }),
                },
            })
        )

        expect(
            await counterValue(kafkaProducerBrokerTxErrorsTotal, { producer_name: 'DEFAULT', broker: 'kafka-1:9092/1' })
        ).toBe(2)
        expect(
            await counterValue(kafkaProducerBrokerTxErrorsTotal, { producer_name: 'DEFAULT', broker: 'kafka-2:9092/2' })
        ).toBe(5)
    })

    it('swallows invalid JSON', () => {
        const tracker = new ProducerStatsTracker('DEFAULT')
        expect(() => tracker.track('not json')).not.toThrow()
    })
})
