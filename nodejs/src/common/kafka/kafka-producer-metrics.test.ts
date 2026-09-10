import { Gauge, register } from 'prom-client'

import {
    ProducerStatsTracker,
    kafkaProducerAnyBrokersDown,
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

    it('flags any broker not UP via kafkaProducerAnyBrokersDown', async () => {
        const tracker = new ProducerStatsTracker('DEFAULT')

        tracker.track(
            makeStats({
                brokers: {
                    'kafka-1:9092/1': { state: 'UP' },
                    'kafka-2:9092/2': { state: 'DOWN' },
                },
            })
        )

        expect(await gaugeValue(kafkaProducerAnyBrokersDown, { producer_name: 'DEFAULT' })).toBe(1)
    })

    it('reports zero when all known brokers are UP', async () => {
        const tracker = new ProducerStatsTracker('DEFAULT')

        tracker.track(
            makeStats({
                brokers: { 'kafka-1:9092/1': { state: 'UP' }, 'kafka-2:9092/2': { state: 'UP' } },
            })
        )

        expect(await gaugeValue(kafkaProducerAnyBrokersDown, { producer_name: 'DEFAULT' })).toBe(0)
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
