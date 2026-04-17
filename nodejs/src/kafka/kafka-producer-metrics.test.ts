import { Counter, Gauge, register } from 'prom-client'

import {
    ProducerStatsTracker,
    kafkaProducerBrokerDisconnectsTotal,
    kafkaProducerBrokerInflightRequests,
    kafkaProducerBrokerOutbufMessages,
    kafkaProducerBrokerRequestTimeoutsTotal,
    kafkaProducerBrokerRttP99Microseconds,
    kafkaProducerBrokerThrottleP99Milliseconds,
    kafkaProducerBrokerTxErrorsTotal,
    kafkaProducerBrokerTxRetriesTotal,
    kafkaProducerQueueBytes,
    kafkaProducerQueueMaxBytes,
    kafkaProducerQueueMaxMessages,
    kafkaProducerQueueMessages,
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
        brokers: {},
        ...overrides,
    })
}

function makeBroker(overrides: Record<string, any> = {}): any {
    return {
        name: 'kafka-1:9092/1',
        nodeid: 1,
        outbuf_msg_cnt: 0,
        waitresp_cnt: 0,
        tx: 0,
        txerrs: 0,
        txretries: 0,
        req_timeouts: 0,
        disconnects: 0,
        rtt: { p99: 0 },
        throttle: { p99: 0 },
        ...overrides,
    }
}

describe('ProducerStatsTracker', () => {
    beforeEach(() => {
        register.resetMetrics()
    })

    it('sets top-level queue gauges', async () => {
        const tracker = new ProducerStatsTracker('DEFAULT')

        tracker.track(makeStats({ msg_cnt: 42, msg_size: 9000, msg_max: 100_000, msg_size_max: 1_000_000 }))

        const labels = { producer_name: 'DEFAULT' }
        expect(await gaugeValue(kafkaProducerQueueMessages, labels)).toBe(42)
        expect(await gaugeValue(kafkaProducerQueueBytes, labels)).toBe(9000)
        expect(await gaugeValue(kafkaProducerQueueMaxMessages, labels)).toBe(100_000)
        expect(await gaugeValue(kafkaProducerQueueMaxBytes, labels)).toBe(1_000_000)
    })

    it('sets per-broker gauges including rtt and throttle p99', async () => {
        const tracker = new ProducerStatsTracker('DEFAULT')

        tracker.track(
            makeStats({
                brokers: {
                    'kafka-1:9092/1': makeBroker({
                        outbuf_msg_cnt: 5,
                        waitresp_cnt: 3,
                        rtt: { p99: 1234 },
                        throttle: { p99: 50 },
                    }),
                },
            })
        )

        const labels = { producer_name: 'DEFAULT', broker: 'kafka-1:9092/1' }
        expect(await gaugeValue(kafkaProducerBrokerOutbufMessages, labels)).toBe(5)
        expect(await gaugeValue(kafkaProducerBrokerInflightRequests, labels)).toBe(3)
        expect(await gaugeValue(kafkaProducerBrokerRttP99Microseconds, labels)).toBe(1234)
        expect(await gaugeValue(kafkaProducerBrokerThrottleP99Milliseconds, labels)).toBe(50)
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
            makeStats({ brokers: { 'kafka-1:9092/1': makeBroker({ txerrs: 5, txretries: 10, req_timeouts: 1 }) } })
        )
        tracker.track(
            makeStats({ brokers: { 'kafka-1:9092/1': makeBroker({ txerrs: 8, txretries: 12, req_timeouts: 1 }) } })
        )

        expect(await counterValue(kafkaProducerBrokerTxErrorsTotal, labels)).toBe(3)
        expect(await counterValue(kafkaProducerBrokerTxRetriesTotal, labels)).toBe(2)
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
