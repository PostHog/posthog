import { Message, TopicPartitionOffset } from 'node-rdkafka'
import { register } from 'prom-client'

import {
    CAPTURE_TIMESTAMP_HEADER,
    CaptureWatermark,
    CapturedRecord,
    capturedRecords,
    releasingOffsetStore,
} from './capture-watermark'

const TOPIC = 'session_replay_image_scrub'
const MINUTE_MS = 60_000

function record(offset: number, capturedAtMs: number | undefined, overrides: Partial<CapturedRecord> = {}) {
    return { topic: TOPIC, partition: 0, offset, data: 'inline_images' as const, capturedAtMs, ...overrides }
}

function stored(offset: number, partition = 0): TopicPartitionOffset[] {
    return [{ topic: TOPIC, partition, offset }]
}

function message(offset: number, capturedAtMs: number, partition = 0): Message {
    return {
        topic: TOPIC,
        partition,
        offset,
        value: null,
        size: 0,
        headers: [{ [CAPTURE_TIMESTAMP_HEADER]: Buffer.from(String(capturedAtMs)) }],
    }
}

describe('CaptureWatermark', () => {
    it('holds a batch until a stored offset passes its last record, then keeps it for the finished window', () => {
        const watermark = new CaptureWatermark('held', 10 * MINUTE_MS)
        watermark.hold([record(0, 2_000), record(1, 1_000)])
        // librdkafka reports a record without a timestamp as -1, and a record without the header has none.
        watermark.hold([record(2, 3_000), record(3, 4_000), record(4, -1), record(5, undefined)])

        watermark.release(stored(3), 0)
        expect(watermark.snapshot(20 * MINUTE_MS)).toEqual([
            { topic: TOPIC, partition: 0, data: 'inline_images', capturedAtMs: 3_000 },
        ])

        watermark.release(stored(4), 20 * MINUTE_MS)
        expect(watermark.snapshot(25 * MINUTE_MS)[0].capturedAtMs).toBe(3_000)
        // A partition that delivers nothing more keeps its last value, so a stalled consumer still shows its lag.
        expect(watermark.snapshot(60 * MINUTE_MS)[0].capturedAtMs).toBe(3_000)
    })

    it('reports each kind of data on a partition apart, and releases them together', () => {
        const watermark = new CaptureWatermark('kinds', 0)
        watermark.hold([record(0, 9_000), record(1, 1_000, { data: 'url_images' }), record(2, 5_000, { partition: 1 })])

        expect(watermark.snapshot(0)).toEqual([
            { topic: TOPIC, partition: 0, data: 'inline_images', capturedAtMs: 9_000 },
            { topic: TOPIC, partition: 0, data: 'url_images', capturedAtMs: 1_000 },
            { topic: TOPIC, partition: 1, data: 'inline_images', capturedAtMs: 5_000 },
        ])

        watermark.hold([record(3, 10_000), record(4, 11_000, { data: 'url_images' })])
        watermark.release(stored(3), 0)
        watermark.forget([{ topic: TOPIC, partition: 1 }])
        expect(watermark.snapshot(1)).toEqual([
            { topic: TOPIC, partition: 0, data: 'inline_images', capturedAtMs: 10_000 },
            { topic: TOPIC, partition: 0, data: 'url_images', capturedAtMs: 11_000 },
        ])
    })

    it('does not release offsets that Kafka refused to store', () => {
        const watermark = new CaptureWatermark('refused', 0)
        const store = releasingOffsetStore(
            {
                offsetsStore: () => {
                    throw new Error('Local: Erroneous state')
                },
            },
            watermark
        )
        watermark.hold(capturedRecords([message(0, 1_000), message(1, 2_000)], () => 'event_metadata'))
        watermark.hold(capturedRecords([message(2, 3_000)], () => 'event_metadata'))

        expect(() => store.offsetsStore(stored(2))).toThrow('Erroneous state')
        expect(watermark.snapshot(Date.now() + 1)[0].capturedAtMs).toBe(1_000)
    })

    it('exports the watermark in seconds for each partition and kind of data', async () => {
        new CaptureWatermark('exported', 0).hold([record(7, 1_790_000_000_500, { partition: 17, data: 'url_images' })])

        const metric = await register.getSingleMetric('ml_replay_capture_watermark_timestamp_seconds')!.get()

        expect(metric.values).toContainEqual({
            labels: { partition: '17', data: 'url_images' },
            value: 1_790_000_000.5,
        })
    })
})
