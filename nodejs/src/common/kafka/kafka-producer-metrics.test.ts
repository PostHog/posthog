import { Gauge, register } from 'prom-client'

import {
    ProducerStatsTracker,
    kafkaProducerBrokerLatencySeconds,
    kafkaProducerBrokers,
    kafkaProducerBusiestBrokerRequestsInFlight,
    kafkaProducerCallbackQueueDepth,
    kafkaProducerQueueBytes,
    kafkaProducerQueueMaxBytes,
    kafkaProducerQueueMaxMessages,
    kafkaProducerQueueMessages,
    kafkaProducerRequestsInFlight,
    kafkaProducerRequestsQueued,
    kafkaProducerTopicBatchCountAvg,
    kafkaProducerTopicBatchSizeBytesAvg,
} from './kafka-producer-metrics'

async function gaugeValue(metric: Gauge<string>, labels: Record<string, string>): Promise<number | undefined> {
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

    it('counts brokers per librdkafka state', async () => {
        const tracker = new ProducerStatsTracker('DEFAULT')

        tracker.track(
            makeStats({
                brokers: {
                    'kafka-1:9092/1': { nodeid: 1, state: 'UP' },
                    'kafka-2:9092/2': { nodeid: 2, state: 'UP' },
                    'kafka-3:9092/3': { nodeid: 3, state: 'DOWN' },
                    'kafka-4:9092/4': { nodeid: 4, state: 'INIT' },
                },
            })
        )

        expect(await gaugeValue(kafkaProducerBrokers, { producer_name: 'DEFAULT', state: 'UP' })).toBe(2)
        expect(await gaugeValue(kafkaProducerBrokers, { producer_name: 'DEFAULT', state: 'DOWN' })).toBe(1)
        expect(await gaugeValue(kafkaProducerBrokers, { producer_name: 'DEFAULT', state: 'INIT' })).toBe(1)
    })

    it('excludes bootstrap entries from broker counts', async () => {
        const tracker = new ProducerStatsTracker('DEFAULT')

        tracker.track(
            makeStats({
                brokers: {
                    'kafka-1:9092/bootstrap': { nodeid: -1, state: 'DOWN' },
                    'kafka-1:9092/1': { nodeid: 1, state: 'UP' },
                },
            })
        )

        expect(await gaugeValue(kafkaProducerBrokers, { producer_name: 'DEFAULT', state: 'UP' })).toBe(1)
        expect(await gaugeValue(kafkaProducerBrokers, { producer_name: 'DEFAULT', state: 'DOWN' })).toBeUndefined()
    })

    it('resets a state to zero once no broker is in it any more', async () => {
        const tracker = new ProducerStatsTracker('DEFAULT')

        tracker.track(makeStats({ brokers: { 'kafka-1:9092/1': { nodeid: 1, state: 'DOWN' } } }))
        tracker.track(makeStats({ brokers: { 'kafka-1:9092/1': { nodeid: 1, state: 'UP' } } }))

        expect(await gaugeValue(kafkaProducerBrokers, { producer_name: 'DEFAULT', state: 'DOWN' })).toBe(0)
        expect(await gaugeValue(kafkaProducerBrokers, { producer_name: 'DEFAULT', state: 'UP' })).toBe(1)
    })

    it('rolls up broker requests and latency windows across learned brokers', async () => {
        const tracker = new ProducerStatsTracker('DEFAULT')

        tracker.track(
            makeStats({
                brokers: {
                    'kafka-1:9092/bootstrap': {
                        nodeid: -1,
                        state: 'UP',
                        waitresp_cnt: 100,
                        outbuf_cnt: 100,
                        rtt: { sum: 90_000_000, cnt: 1, p99: 90_000_000 },
                    },
                    'kafka-1:9092/1': {
                        nodeid: 1,
                        state: 'UP',
                        waitresp_cnt: 5,
                        outbuf_cnt: 7,
                        rtt: { sum: 1_200_000, cnt: 3, p99: 600_000 },
                        outbuf_latency: { sum: 0, cnt: 0, p99: 0 },
                    },
                    'kafka-2:9092/2': {
                        nodeid: 2,
                        state: 'UP',
                        waitresp_cnt: 2,
                        outbuf_cnt: 0,
                        rtt: { sum: 200_000, cnt: 1, p99: 200_000 },
                    },
                },
            })
        )

        const labels = { producer_name: 'DEFAULT' }
        expect(await gaugeValue(kafkaProducerRequestsInFlight, labels)).toBe(7)
        expect(await gaugeValue(kafkaProducerBusiestBrokerRequestsInFlight, labels)).toBe(5)
        expect(await gaugeValue(kafkaProducerRequestsQueued, labels)).toBe(7)
        const latency = (name: string, stat: string): Promise<number | undefined> =>
            gaugeValue(kafkaProducerBrokerLatencySeconds, { ...labels, latency: name, stat })
        expect(await latency('round_trip', 'mean')).toBeCloseTo(0.35)
        expect(await latency('round_trip', 'max_p99')).toBeCloseTo(0.6)
        expect(await latency('request_queue', 'mean')).toBe(0)
        expect(await latency('request_queue', 'max_p99')).toBe(0)
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

    it('swallows invalid JSON', () => {
        const tracker = new ProducerStatsTracker('DEFAULT')
        expect(() => tracker.track('not json')).not.toThrow()
    })

    it('swallows payloads that fail schema validation without emitting metrics', async () => {
        const tracker = new ProducerStatsTracker('DEFAULT')
        // msg_cnt should be a number — librdkafka suddenly emitting a string shape
        // means we've drifted. Don't throw, don't emit bogus metrics.
        expect(() => tracker.track(JSON.stringify({ msg_cnt: 'oops' }))).not.toThrow()
        expect(await gaugeValue(kafkaProducerQueueMessages, { producer_name: 'DEFAULT' })).toBeUndefined()
    })

    it('ignores unknown top-level fields', async () => {
        const tracker = new ProducerStatsTracker('DEFAULT')
        tracker.track(makeStats({ msg_cnt: 5, some_new_upstream_field: 'hello' }))
        expect(await gaugeValue(kafkaProducerQueueMessages, { producer_name: 'DEFAULT' })).toBe(5)
    })
})
